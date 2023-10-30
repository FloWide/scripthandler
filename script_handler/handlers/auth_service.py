from optparse import Option
from typing import Any, List, Optional, Sequence, Tuple,Union,Set
from fastapi.responses import Response,JSONResponse
import jwt
from abc import ABC,abstractmethod
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthCredentials, AuthenticationBackend, AuthenticationError, SimpleUser
)

from starlette.requests import HTTPConnection, Request

from script_handler.git.git_service_provider import GitServiceProvider, UserCreationData
from script_handler.git.gitlab_service import GitlabServiceError

from ..models.collections import UserCollection
from ..models.user import UserData

class AuthService(ABC,AuthenticationBackend):

    def __init__(
        self,
        user_collection: UserCollection,
        git_service: GitServiceProvider
    ) -> None:
        super().__init__()
        self._user_collection = user_collection
        self._git_service = git_service

    @abstractmethod
    def decode(self,token: str) -> dict:
        pass
    
    @abstractmethod
    def get_user_id(self,token: Union[str,dict]) -> Optional[Any]:
        pass
    
    @abstractmethod
    def get_permissions(self,token: Union[str,dict]) -> List[str]:
        pass

    @abstractmethod
    def get_user_data(self,token: Union[str,dict]) -> UserData:
        pass
    
    @abstractmethod
    def get_user_creation_data(self,token: Union[str,dict]) -> UserCreationData:
        pass
    
    async def authenticate(self, conn: HTTPConnection) -> Optional[Tuple[AuthCredentials, Any]]: # type ignore
        if conn.url.path.startswith("/public") or conn.scope.get("method") == "OPTIONS": # can't have route based middlewares in fastapi this is the only way to have a public path 
            return AuthCredentials(),None
        token = None

        if conn.headers.get("Authorization"):
            _,token = conn.headers["Authorization"].strip().split(' ')
        else:
            token = conn.query_params.get('token')

        if not token:
            raise AuthenticationError('Missing access token')

        try:
            payload = self.decode(token)
            user_id = self.get_user_id(payload)
            permissions = self.get_permissions(payload)
            user_data = self.get_user_data(payload)
            user = self._user_collection.get_user_by_auth_id(user_id)

            if not user:
                # raise AuthenticationError('User does not exists')
                try:
                    user = await self._git_service.create_user(
                        self.get_user_creation_data(payload)
                    )
                    self._user_collection.new_user(user)
                except GitlabServiceError as e:
                    raise AuthenticationError(e)

            user.set_user_data(user_data)

            return AuthCredentials(permissions),user

        except Exception as e:
            raise AuthenticationError(str(e))

    @staticmethod
    def default_on_error(conn: HTTPConnection, exc: Exception) -> Response:
        return JSONResponse({"error":str(exc)},status_code=400)


class Auth0Service(AuthService):

    def __init__(
        self,
        secret: str,
        audience: str,
        user_collection: UserCollection
    ) -> None:
        super().__init__(user_collection)
        self._secret = secret
        self._audience = audience

    def decode(self,token:str) -> dict:
        return jwt.decode(token,self._secret,algorithms=["HS256"],audience=self._audience)

    def get_user_id(self,token: Union[str,dict]) -> Optional[Any]:
        if isinstance(token,str):
            return self.decode(token).get("sub")
        else:
            return token.get("sub")

    def get_permissions(self,token: Union[str,dict]) -> List[str]:
        if isinstance(token,str):
            return self.decode(token).get("permissions",[]) # type: ignore
        else:
            return token.get("permissions",[]) # type: ignore

class KeyCloakService(AuthService):

    def __init__(
        self,
        public_key:str,
        audience: str,
        user_collection: UserCollection,
        git_service: GitServiceProvider
    ) -> None:
        super().__init__(user_collection,git_service)
        self._public_key = public_key
        self._audience = audience

    def decode(self, token: str) -> dict:
        return jwt.decode(token,self._public_key,algorithms=["RS256"],audience=self._audience)

    def get_user_id(self, token: Union[str, dict]) -> Optional[Any]:
        if isinstance(token,str):
            return self.decode(token).get("preferred_username")
        else:
            return token.get("preferred_username")

    def get_permissions(self, token: Union[str, dict]) -> List[str]:
        if isinstance(token,str):
            token = self.decode(token)
        return token.get("resource_access",{}).get(self._audience,{}).get("roles",[]) # type: ignore

    def get_user_data(self, token: Union[str, dict]) -> UserData:
        if isinstance(token,str):
            return UserData(**self.decode(token).get("user_data",{}))
        else:
            return UserData(**token.get("user_data",{}))

    def get_user_creation_data(self, token: Union[str, dict]) -> UserCreationData:
        if isinstance(token,str):
            data = self.decode(token)
        else:
            data = token
        return UserCreationData(
            data["email"],
            data["preferred_username"],
            data["name"],
            data["preferred_username"],
            "openid_connect"
        )