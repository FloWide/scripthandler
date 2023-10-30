
from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from ..models.collections import ObjCollection,create_extra_remover,create_extra_adder
from ..models.service import Service, ServiceModel
from .utils import HandlerClass,api_route

from starlette.authentication import requires

class ServiceHandler(HandlerClass):


    def __init__(
        self,
        services: ObjCollection[Service]
    ) -> None:
        self._services = services
        self._router = APIRouter(
            tags=["Services"],
            redirect_slashes=False,
            prefix='/service',
            dependencies=[
                Depends(create_extra_remover(services)),
                Depends(create_extra_adder(services)),
                Depends(self._service_by_id)
            ]
        )

    @api_route('',methods=["GET"])
    def get_services(self,request: Request):
        return self._services.get_all_for_user(request.user)

    @api_route('/{name}')
    def get_by_name(self,request: Request,name: str):
        return self._services.get_by_name_for_user(request.user,name)

    @api_route('/{name}/{version}',methods=["GET"],response_model=ServiceModel)
    def get_service(self,request: Request):
        return request.state.service

    requires(['manage:service'])
    @api_route('/{name}/{version}/enable',methods=["POST"],response_model=ServiceModel)
    async def enable_service(self,request: Request):
        service: Service = request.state.service
        await service.set_enabled(True,True)
        return service

    requires(['manage:service'])
    @api_route('/{name}/{version}/disable',methods=["POST"],response_model=ServiceModel)
    async def disable_service(self,request: Request):
        service: Service = request.state.service
        await service.set_enabled(False,True)
        return service

    @api_route('/{name}/{version}/logs',methods=["GET"],response_class=PlainTextResponse)
    async def get_logs(self,request: Request,limit: Optional[int] = 200):
        service: Service = request.state.service
        return await service.get_logs(limit)

    requires(['manage:service'])
    @api_route('/{name}/{version}/restart',methods=["POST"],response_model=ServiceModel)
    async def restart_service(self,request: Request):
        service: Service = request.state.service
        await service.restart()
        return service

    
    def _service_by_id(self,request: Request,name: Optional[str] = None,version: Optional[str] = None):
        if not (name and version):
            return

        if version == 'latest':
            service = self._services.get_latest_for_user_named(request.user,name)
        else:
            service = self._services.get_object_for_user(request.user,name,version)
        if not service:
            raise HTTPException(404,"Service not found")

        request.state.service = service


    @property
    def router(self) -> APIRouter:
        return self._router