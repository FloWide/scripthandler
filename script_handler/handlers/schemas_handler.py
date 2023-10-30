

from asyncio import proactor_events
from .utils import HandlerClass,api_route
from fastapi import APIRouter,Request

from ..models.app_config import AppConfigsJson
import json

class SchemasHandler(HandlerClass):

    def __init__(self) -> None:
        
        self._router = APIRouter(
            prefix='/schemas',
            tags=['Schemas']
        )

    @api_route('/appconfig.schema',methods=["GET"])
    def app_config_schema(self,request: Request):
        return json.loads(AppConfigsJson.schema_json())


    @property
    def router(self):
        return self._router
