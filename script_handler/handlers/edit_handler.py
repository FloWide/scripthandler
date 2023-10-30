

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import os
from typing import Any, List, Literal, Optional, final
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from loguru import logger

from script_handler.runner.runner_base import Runner

from ..runner.runner_factory import RunnerFactory
from ..models.collections import RepositoryCollection

from ..models.repository import Repository, RepositoryFileEntry

from .utils import HandlerClass, RunnerWebsocketConnector, api_route, websocket_route

from starlette.authentication import requires

from pylsp.python_lsp import PythonLSPServer, JsonRpcStreamReader, JsonRpcStreamWriter, Endpoint, MAX_WORKERS

import logging
import re


@dataclass
class EditMsg:
    class Action(str, Enum):
        CREATE = 'create'
        DELETE = 'delete'
        MOVE = 'move'
        UPDATE = 'update'

    action: Action
    file_path: str
    previous_path: str
    content: str
    base64encoded: bool


@dataclass
class ControlMessage:
    class Action(str, Enum):
        RUN = 'run'
        STOP = 'stop'

    action: Action
    type: Optional[Literal['python'] | Literal["streamlit"]] = None
    file: str = None
    env: Optional[dict] = None
    cli_args: Optional[list] = None


@dataclass
class WebsocketMessage:
    type: str
    data: dict


class EditWebsocketHandler:

    STREAMLIT_IMPORT_REGEX = re.compile('((import)|(from)) +streamlit')

    def __init__(
        self,
        ws: WebSocket,
        repo: Repository,
        python_runner: Runner,
        streamlit_runner: Runner
    ) -> None:
        self._ws = ws
        self._repo = repo
        self._python_runner = python_runner
        self._streamlit_runner = streamlit_runner
        self._active_runner: Runner = None
        self._runner_reader_task = None
        self._runner_wait_task = None

    async def serve(self):
        try:
            await self.ws_reader_task()
        except WebSocketDisconnect:
            logging.info("Closing edit websocket")
        finally:
            await self.stop_runner()

    async def cancel(self, code: int = 1000, reason: str = None):
        await self.stop_runner()
        await self._ws.close(code, reason)

    async def ws_reader_task(self):
        async for ws_message in self._ws.iter_json():
            message = WebsocketMessage(**ws_message)
            if message.type == 'edit':
                await self.on_edit_message(EditMsg(**message.data))
            elif message.type == 'control':
                await self.on_control_message(ControlMessage(**message.data))
            elif message.type == 'stream':
                await self.on_stream_message(message.data)
            else:
                logger.warning(
                    f"Invalid message type received: {message.type}")

    async def on_edit_message(self, msg: EditMsg):
        if msg.action == EditMsg.Action.CREATE:
            await self._repo.create_file(msg.file_path, msg.content, msg.base64encoded)
        elif msg.action == EditMsg.Action.UPDATE:
            await self._repo.update_file(msg.file_path, msg.content, msg.base64encoded)
        elif msg.action == EditMsg.Action.MOVE:
            self._repo.move_file(msg.previous_path, msg.file_path)
        elif msg.action == EditMsg.Action.DELETE:
            self._repo.delete(msg.file_path)

        await self.send_edit_message({
            "files": self._repo.get_file_tree(),
            "git_status": self._repo.git_status()
        })

    async def on_control_message(self, msg: ControlMessage):
        if msg.action == ControlMessage.Action.RUN:
            if self._active_runner and self._active_runner.is_running:
                await self.stop_runner()
            await self._repo.update_app_config()
            type = msg.type if msg.type else await self.guess_type(msg.file)
            self._active_runner = self._python_runner if type == 'python' else self._streamlit_runner
            await self._active_runner.run(
                msg.file, 
                {**msg.env,**{"RELEASE_MODE":False}} if msg.env else {"RELEASE_MODE":False},
                msg.cli_args
            )
            self._runner_wait_task = asyncio.create_task(
                self.runner_wait_task())
            self._runner_reader_task = asyncio.create_task(
                self.runner_reader_task())
            await self.send_control_message({
                "status": "active",
                "port": self._active_runner.port,
                "type": type
            })
        elif msg.action == ControlMessage.Action.STOP:
            await self.stop_runner()
            self._active_runner = None

    async def on_stream_message(self, msg: str):
        if not self._active_runner:
            return
        await self._active_runner.streams.write(msg.encode())

    async def send_edit_message(self, data: Any):
        await self._ws.send_json({
            "type": "edit",
            "data": data
        })

    async def send_control_message(self, data: Any):
        await self._ws.send_json({
            "type": "control",
            "data": data
        })

    async def send_stream_message(self, data: Any):
        await self._ws.send_json({
            "type": "stream",
            "data": data
        })

    async def runner_reader_task(self):
        if not self._active_runner or not self._active_runner.is_running:
            return
        try:
            async for data in self._active_runner.streams.stream_read():
                await self.send_stream_message(data.decode())
        except asyncio.CancelledError:
            pass

    async def runner_wait_task(self):
        if not self._active_runner:
            return
        try:
            exit_code = await self._active_runner.wait()
            await self.send_stream_message(f"Process exited with code: {exit_code}\n\r")
            await self.send_control_message({
                "status": "inactive",
                "exit_code": exit_code
            })
        except asyncio.CancelledError:
            pass

    async def stop_runner(self):
        if not self._active_runner:
            return
        try:
            if self._active_runner.is_running:
                await self._active_runner.terminate(10)
        except asyncio.TimeoutError:
            if self._active_runner.is_running:
                await self._active_runner.kill()
        finally:
            if self._runner_reader_task:
                self._runner_reader_task.cancel()
            if self._runner_wait_task:
                self._runner_wait_task.cancel()

    async def guess_type(self, file: str):
        content = await self._repo.get_file_content(file)
        if EditWebsocketHandler.STREAMLIT_IMPORT_REGEX.match(content):
            return 'streamlit'
        else:
            return 'python'


class EditHandler(HandlerClass):

    def __init__(
        self,
        repo_collection: RepositoryCollection,
        runner_factory: RunnerFactory,
        venv_activator: str,
        enable_lsp: bool
    ) -> None:
        self._repo_collection = repo_collection
        self._runner_factory = runner_factory
        self._router = APIRouter(
            redirect_slashes=False,
            tags=["Edit"]
        )
        self._venv_activator = venv_activator
        self._enable_lsp = enable_lsp

    @requires(['edit:repo'])
    @api_route('/filetree', methods=["GET"], response_model=List[RepositoryFileEntry])
    def get_file_tree(self, request: Request):
        repo: Repository = request.state.repo
        return repo.get_file_tree()

    @requires(['edit:repo'])
    @api_route('/file/{path:path}', methods=["GET"], response_class=FileResponse)
    def get_file_content(self, request: Request, path: str):
        logging.debug(f"Getting file with path {path}")
        repo: Repository = request.state.repo
        
        full_path = os.path.join(repo.get_root_path(),path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404)
        return FileResponse(
            full_path,
            headers={
                'Cache-Control':'no-store'
            },
            filename=full_path[full_path.rfind('/')+1:]
        )

    @requires(['edit:repo'])
    @websocket_route('/ws')
    async def websocket(self, websocket: WebSocket, id: int):
        await websocket.accept()
        try:
            repo: Repository = self._repo_by_id(websocket, id)
        except HTTPException as e:
            await websocket.close(4000, "Repository not found")
            return

        force = websocket.query_params.get("force", False)
        editing_ws = repo.get_edit_ws()
        if editing_ws and not force:
            await websocket.close(4000, "Repository is already being edited")
            return

        if editing_ws and force:
            try:
                await editing_ws.cancel(1001, "Connection force closed by other endpoint")
            except Exception as e:
                logger.warning(str(e))
            finally:
                repo.set_edit_ws(None)

        handler = EditWebsocketHandler(
            websocket,
            repo,
            self._runner_factory.create_python_runner(repo.get_root_path()),
            self._runner_factory.create_streamlit_runner(repo.get_root_path())
        )
        repo.set_edit_ws(handler)
        await handler.serve()
        repo.set_edit_ws(None)

    @requires(['edit:repo'])
    @websocket_route('/shell')
    async def shell(self, websocket: WebSocket, id: int):
        await websocket.accept()
        try:
            repo: Repository = self._repo_by_id(websocket, id)
        except HTTPException as e:
            await websocket.close(4000, "Repository not found")
            return
        shell = self._runner_factory.create_python_shell_runner(
            repo.get_root_path())
        handler = RunnerWebsocketConnector(websocket, shell)
        await shell.run(None)
        try:
            await handler.serve()
        except WebSocketDisconnect:
            await shell.terminate()

    @requires(['edit:repo'])
    @websocket_route('/lsp')
    async def lsp(self, websocket: WebSocket, id: int):

        if not self._enable_lsp:
            return

        await websocket.accept()
        try:
            repo: Repository = self._repo_by_id(websocket, id)
        except HTTPException as e:
            await websocket.close(4000, "Repository not found")
            return

        with ThreadPoolExecutor(2) as tpool:
            def send_message(message):
                try:
                    asyncio.run(websocket.send_json(message))
                except Exception as e:  # pylint: disable=broad-except
                    logging.exception(
                        "Failed to write message %s, %s", message, str(e))

            try:
                lsp = WebSocketLsp(rx=None, tx=None, consumer=send_message,
                                   venv_activator=self._venv_activator, root_path=repo.get_root_path())
                async for msg in websocket.iter_json():
                    await asyncio.get_running_loop().run_in_executor(tpool, lsp.consume, msg)
            finally:
                logging.debug("Disconnected, closing lsp")
                lsp.m_exit()

    # this is needed only for a workaround in websocket connections
    def _repo_by_id(self, request, id):
        repo = (self._repo_collection.get_user_repos(
            request.user) or {}).get(id)

        if not repo:
            raise HTTPException(404, "Repository not found")
        return repo

    @property
    def router(self):
        return self._router


class WebSocketLsp(PythonLSPServer):

    def __init__(self, rx, tx, venv_activator: str, consumer, check_parent_process=False, root_path='/'):
        self.workspace = None
        self.config = None
        self.root_uri = None
        self.watching_thread = None
        self.workspaces = {}
        self.uri_workspace_mapper = {}
        self.root_path = root_path
        self._venv_activator = venv_activator

        self._check_parent_process = check_parent_process

        if rx is not None:
            self._jsonrpc_stream_reader = JsonRpcStreamReader(rx)
        else:
            self._jsonrpc_stream_reader = None

        if tx is not None:
            self._jsonrpc_stream_writer = JsonRpcStreamWriter(tx)
        else:
            self._jsonrpc_stream_writer = None

        # if consumer is None, it is assumed that the default streams-based approach is being used
        if consumer is None:
            self._endpoint = Endpoint(
                self, self._jsonrpc_stream_writer.write, max_workers=MAX_WORKERS)
        else:
            self._endpoint = Endpoint(self, consumer, max_workers=MAX_WORKERS)

        self._dispatchers = []
        self._shutdown = False

    def consume(self, message):
        """Entry point for consumer based server. Alternative to stream listeners."""
        # assuming message will be JSON
        self._endpoint.consume(message)

    def m_exit(self, **_kwargs):
        self._endpoint.shutdown()
        if self._jsonrpc_stream_reader is not None:
            self._jsonrpc_stream_reader.close()
        if self._jsonrpc_stream_writer is not None:
            self._jsonrpc_stream_writer.close()

    def m_initialize(self, processId=None, rootUri=None, rootPath=None, initializationOptions=None, workspaceFolders=None, **_kwargs):
        ret = super().m_initialize(processId, self.root_path, self.root_path,
                                   initializationOptions, workspaceFolders, **_kwargs)
        venv_python = os.path.join(os.path.dirname(self._venv_activator),'python')
        self.m_workspace__did_change_configuration({
            "pylsp": {
                "plugins": {
                    "jedi": {
                        "environment": venv_python,
                    },
                    "pylsp_mypy":{
                        "enabled":True,
                        "live_mode":False,
                        "dmypy":True,
                        "overrides":["--python-executable",venv_python,True]
                    },
                    "pycodestyle":{
                        "ignore":["E501"]
                    }
                },
            }
        })
        return ret
