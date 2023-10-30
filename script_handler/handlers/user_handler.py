


from .utils import HandlerClass, api_route
from ..models.collections import UserCollection
from ..models.user import User
from typing import Dict
from fastapi import APIRouter, Depends, Request

from starlette.authentication import requires

class UserHandler(HandlerClass):


    def __init__(
        self,
        user_collection: UserCollection
    ) -> None:
        self._user_collection = user_collection
        self._router = APIRouter(
            prefix='/user',
            redirect_slashes=False,
            tags=["User"]
        )

    @requires(['read:user'])
    @api_route(path='',methods=["GET"])
    def get_users(self,request: Request):
        return self._user_collection.users

    @api_route(path='/me',methods=["GET"])
    def get_logged_in(self,request: Request):
        return request.user

    @property
    def router(self):
        return self._router