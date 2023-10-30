

from .utils import HandlerClass,api_route

from ..models.collections import ObjCollection, UserCollection
from ..models.script import Script
from ..models.service import Service

from fastapi import APIRouter,Depends,Request,HTTPException,Response

class WebHooksHandlers(HandlerClass):

    def __init__(
        self,
        secret: str,
        scripts: ObjCollection[Script],
        services: ObjCollection[Service],
        users: UserCollection
    ) -> None:
        self._scripts = scripts
        self._services = services
        self._secret = secret
        self._users = users

        self._router = APIRouter(
            dependencies=[Depends(self._check_secret)],
            prefix='/webhooks',
            redirect_slashes=False
        )

    @api_route('/run_init_script',methods=["POST"])
    async def run_init_script(self,request: Request, username:str, script_name: str, version: str = "latest"):
        user = self._users.get_user_by_username(username)

        if not user:
            raise HTTPException(status_code=404,detail=f"User not found {username}")

        if version == 'latest':
            script = self._scripts.get_latest_for_user_named(user,script_name)
        else:
            script = self._scripts.get_object_for_user(user,script_name,version)

        if not script:
            raise HTTPException(status_code=404,detail=f"Not found script {script_name}")
        
        await script.run()
        exit_code = await script.runner.wait()
        if exit_code != 0:
            raise HTTPException(status_code=500,detail=f"Script exited with exit code {exit_code}")

        return Response(status_code=200)

    @property
    def router(self) -> APIRouter:
        return self._router

    def _check_secret(self,request: Request):
        secret = request.headers.get('X-Webhook-Secret')
        if secret != self._secret:
            raise HTTPException(status_code=403,detail="Invalid secret")