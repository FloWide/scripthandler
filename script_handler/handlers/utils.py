import asyncio
import functools
from abc import ABCMeta,abstractmethod
from typing import Any, Callable, Concatenate, List, Optional, ParamSpec, Type, TypeVar, final
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ..runner.runner_base import Runner, RunnerStream

import logging



T = TypeVar('T')
P = ParamSpec('P')


def take_annotation_from(this: Callable[Concatenate[APIRouter,str,Any,P], Optional[T]]) -> Callable[[Callable], Callable[Concatenate[str,P], Optional[T]]]:
    def decorator(real_function: Callable) -> Callable[Concatenate[str,P], Optional[T]]:
        def new_function(*args: P.args, **kwargs: P.kwargs) -> Optional[T]:
            return real_function(*args, **kwargs)

        return new_function
    return decorator


class ApiRouteHandlerMeta(ABCMeta):
    def __call__(cls, *args: Any, **kwds: Any) -> Any:
        inst = ABCMeta.__call__(cls,*args,**kwds)
        ApiRouteHandlerMeta.__bootstrap_routes(inst)
        return inst

    def __bootstrap_routes(self: Any):
        for name in dir(self):
            obj = getattr(self,name)
            if callable(obj) and hasattr(obj,"__router_details__"):
                details = getattr(obj,"__router_details__")
                if details["type"] == "http":
                    self.router.add_api_route(details["path"],obj,**details["kwargs"])
                elif details["type"] == "ws":
                    self.router.add_api_websocket_route(details["path"],obj,**details["kwargs"])

class HandlerClass(metaclass=ApiRouteHandlerMeta):

    @property
    @abstractmethod
    def router(self) -> APIRouter:
        pass

@take_annotation_from(APIRouter.add_api_route)
def api_route(path: str,**kwargs):
    def decorator(func: Callable):
        setattr(func,"__router_details__",{
        "path":path,
        "kwargs":kwargs,
        "type":'http'
        })
        return func
    return decorator

def websocket_route(path: str,**kwargs):
    def decorator(func: Callable):
        setattr(func,"__router_details__",{
        "path":path,
        "kwargs":kwargs,
        "type":'ws'
        })
        return func
    return decorator


class RunnerWebsocketConnector:

    def __init__(
        self,
        ws: WebSocket,
        runner: Runner
    ) -> None:
        self._ws = ws
        self._runner = runner
        self._task_futures = None

    async def serve(self):
        self._task_futures = asyncio.gather(
            self.reader_task(),
            self.writer_task(),
            self.wait_task()
        )
        try:
            await self._task_futures
        except asyncio.exceptions.CancelledError:
            pass
        self._task_futures = None

    async def reader_task(self):
        async for data in self._runner.streams.stream_read():
            logging.debug(f"Sending message: {data}")
            await self._ws.send_bytes(data)

    async def writer_task(self):
        async for message in self._ws_iter_raw():
            logging.debug(f"Received message {message}")
            if message.get("bytes"):
                await self._runner.streams.write(message.get("bytes"))
            elif message.get("text"):
                await self._runner.streams.write(message.get("text").encode())

    async def wait_task(self):
        exit_code = await self._runner.wait()
        await self._ws.send_text(f"Process exited with code: {exit_code}\n\r")
        await self._ws.close(reason=f"Process exited with code: {exit_code}")

    async def _ws_iter_raw(self):
        try:
            while self._ws.client_state == WebSocketState.CONNECTED:
                yield await self._ws.receive()
        except Exception as e:
            logging.warning("Exception in websocket" + str(e))
        finally:
            if self._task_futures:
                self._task_futures.cancel()

