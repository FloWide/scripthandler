from abc import ABC, abstractmethod
from ..models import Repository, User
from typing import Any, Dict, List
from dataclasses import dataclass

@dataclass
class UserCreationData:
    email: str
    username: str
    name :str
    auth_id: str
    auth_provider: str

class GitServiceProvider(ABC):

    @abstractmethod
    async def create_user(self,data: UserCreationData) -> User:
        pass

    @abstractmethod
    async def get_user(self, id: Any) -> User:
        pass

    @abstractmethod
    async def get_all_users(self) -> List[User]:
        pass
    
    @abstractmethod
    async def get_all_repositories(self) -> List[Repository]:
        pass

    @abstractmethod
    async def create_raw_repository(self,user: User, repository_name: str,**kwargs) -> Dict[str,Any]:
        pass
    
    @abstractmethod
    async def create_repository(self, user: User, repository_name: str,**kwargs) -> Repository:
        pass
    
    @abstractmethod
    async def delete_repository_by_id(self,id: Any):
        pass

    @abstractmethod
    async def delete_repository(self, repo: Repository):
        pass

    @abstractmethod
    async def get_repository(self, owner: User, repo_id: str) -> Repository:
        pass
    
    @abstractmethod
    async def get_repository_by_id(self,repo_id: str) -> Repository:
        pass

    @abstractmethod
    async def get_user_repositories(self, user: User) -> List[Repository]:
        pass

    @abstractmethod
    async def fork_repository(self, repo: Repository, for_user: User,new_name: str = None):
        pass

    @abstractmethod
    async def close(self):
        pass
