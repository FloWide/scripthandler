
from pydantic import PrivateAttr
from .base_model import BaseModel
from typing import Any, Set
from pygit2 import Signature
from dataclasses import dataclass,field

@dataclass
class UserData:
    allowed_releases: Set[str] = field(default_factory=set)
    allowed_from_user: Set[int] = field(default_factory=set)


class User(BaseModel):
    _auth_id: str = PrivateAttr()
    git_service_id: int
    username: str
    email: str
    _signature: Signature = PrivateAttr()
    
    _user_data: UserData = PrivateAttr()


    def __init__(self,auth_id,**kwargs):
        super().__init__(**kwargs)
        self._auth_id = auth_id
        self._signature = Signature(self.username,self.email)


    def set_user_data(self,data: UserData):
        self._user_data = data

    @property
    def signature(self):
        return self._signature

    @property
    def auth_id(self):
        return self._auth_id

    @property
    def user_data(self):
        return self._user_data
