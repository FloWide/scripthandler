import asyncio
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request,Response, WebSocket

from script_handler.models.app_config import AppType

from ..models.base_model import BaseModel

from ..models.script import Script, ScriptModel
from .utils import HandlerClass, RunnerWebsocketConnector, api_route, websocket_route
from ..models.collections import ObjCollection, create_extra_adder, create_extra_remover
from ..models.user import User

from starlette.authentication import requires
from fastapi.responses import RedirectResponse,FileResponse

class ScriptRunOverrides(BaseModel):
    entry_file: Optional[str]
    env: Optional[Dict[str,str]]
    cli_args: Optional[List[Any]]


class ScriptHandler(HandlerClass):
    
    def __init__(
        self,
        scripts: ObjCollection[Script]
    ) -> None:
        self._router = APIRouter(
            tags=["Scripts"],
            redirect_slashes=False,
            prefix='/script',
            dependencies=[
                Depends(create_extra_remover(scripts)),
                Depends(create_extra_adder(scripts)),
                Depends(self._script_by_id)
            ]
        )
        self._scripts = scripts
    

    @api_route('',methods=["GET"])
    def get_scripts(self,request: Request):
        return self._scripts.get_all_for_user(request.user)

    @api_route('/{name}')
    def get_by_name(self,request: Request,name: str):
        return self._scripts.get_by_name_for_user(request.user,name)

    @api_route('/{name}/{version}',methods=["GET"],response_model=ScriptModel)
    def get_script(self,request: Request):
        return request.state.script

    @api_route('/{name}/{version}/logo',methods=["GET"])
    def logo(self,request: Request):
        script: Script = request.state.script

        logo = script.config.app_icon

        if not logo:
            raise HTTPException(status_code=404)

        if logo.startswith('http'):
            return RedirectResponse(logo)

        path = os.path.join(script.release.root_path,logo)
        if not os.path.exists(path):
            raise HTTPException(status_code=404)

        return FileResponse(path)



    @requires(['run:script'])
    @api_route('/{name}/{version}/run',methods=["POST"],response_model=ScriptModel)
    async def run_script(self,request: Request,overrides: Optional[ScriptRunOverrides] = None):
        script: Script = request.state.script

        if script.runner.is_running:
            raise HTTPException(400,"Script is already running")

        if overrides:
            await script.run(overrides.entry_file,overrides.env,overrides.cli_args)
        else:
            await script.run()
        return script

    @requires(['run:script'])
    @api_route('/{name}/{version}/stop',methods=["POST"])
    async def stop_script(self,request: Request):
        script: Script = request.state.script

        if not script.runner.is_running:
            raise HTTPException(400,"Script is not running")
        try:
            await script.terminate()
        except asyncio.TimeoutError:
            await script.kill()
        return script

    @requires(['run:script'])
    @api_route('/{name}/{version}/kill',methods=["POST"])
    async def kill_script(self,request: Request):
        script: Script = request.state.script
        if not script.runner.is_running:
            raise HTTPException(400,"Script is not running")
        await script.kill()
        return script

    @requires(['run:script'])
    @websocket_route('/{name}/{version}/output')
    async def output_stream(self,websocket: WebSocket,name: str,version: str):
        await websocket.accept()
        if version == 'latest':
            script = self._scripts.get_latest_for_user_named(websocket.user,name)
        else:
            script = self._scripts.get_object_for_user(websocket.user,name,version)
        if not script:
            await websocket.close(reason="Script not found")            
            return

        handler = RunnerWebsocketConnector(websocket,script.runner)
        try:
            await script.runner.run_start_event.wait()
        except asyncio.CancelledError:
            await websocket.close()
            return
        await handler.serve()
        
    def _script_by_id(self,request: Request,name: Optional[str] = None,version: Optional[str] = None):
        if not (name and version):
            return

        if version == 'latest':
            script = self._scripts.get_latest_for_user_named(request.user,name)
        else:
            script = self._scripts.get_object_for_user(request.user,name,version)
        if not script:
            raise HTTPException(404,"Script not found")

        request.state.script = script

    @property
    def router(self) -> APIRouter:
        return self._router