import asyncio
from typing import Any, Dict, List, Union
from .git_service_provider import GitServiceProvider, UserCreationData
from ..models import User,Repository
from pygit2 import Signature
from aiohttp import ClientSession

class GitlabServiceError(RuntimeError):
    pass

class GitlabService(GitServiceProvider):
    

    def __init__(self,gitlab_url: str,admin_token: str) -> None:
        self._gitlab_url = gitlab_url
        self._http = ClientSession(
            base_url=gitlab_url,
            headers={"Authorization":f"Bearer {admin_token}"}
        )

    async def create_user(self,data: UserCreationData) -> User:
        data_dict = {
            "email":data.email,
            "username":data.username,
            "name":data.name,
            "extern_uid":data.auth_id,
            "provider":data.auth_provider,
            "reset_password":True
        }
        async with self._http.post(f"/api/v4/users",data=data_dict) as r:
            if not (r.status >= 200 and r.status < 300):
                raise GitlabServiceError(await r.text())

            return transform_user_data(await r.json()) # type: ignore

    async def create_raw_repository(self,user: User, repository_name: str,**kwargs) -> Dict[str,Any]:
        async with self._http.post(f"/api/v4/projects/user/{user.git_service_id}",data={**{"name":repository_name},**kwargs}) as r:
            if not (r.status >= 200 and r.status < 300):
                raise GitlabServiceError(await r.text())
        
            return await r.json()

    async def create_repository(self, user: User, repository_name: str,**kwargs) -> Repository:
            return transform_repository_data(await self.create_raw_repository(user,repository_name,**kwargs)) # type: ignore

    async def delete_repository_by_id(self,id: Any):
        async with self._http.delete(f"/api/v4/projects/{id}") as r:
            if not (r.status >= 200 and r.status < 300):
                raise GitlabServiceError(await r.text())

    async def delete_repository(self, repo: Repository):
        await self.delete_repository_by_id(repo.git_service_id)

    async def get_repository(self, owner: User, repo_id: str) -> Repository:
        async with self._http.get(f"/api/v4/users{owner.git_service_id}/{repo_id}") as r:
            if r.status != 200:
                raise GitlabServiceError(await r.text())
 
            repo = transform_repository_data(await r.json())
            if not repo:
                raise GitlabServiceError("Invalid repository")
            return repo

    async def get_repository_by_id(self, repo_id: str) -> Repository:
        async with self._http.get(f"/api/v4/projects/{repo_id}") as r:
            if r.status != 200:
                raise GitlabServiceError(await r.text())
            repo = transform_repository_data(await r.json())
            if not repo:
                raise GitlabServiceError("Invalid repository")
            return repo

    async def get_user_repositories(self, user: User) -> List[Repository]:
        async with self._http.get(f"/api/v4/users/{user.git_service_id}/projects") as r:
            if r.status != 200:
                raise GitlabServiceError(await r.text())

            resp = await r.json()
            return list(
                filter(
                    lambda e: e is not None,
                    map(transform_repository_data,resp) # type: ignore
                )
            )

    async def fork_repository(self, repo: Repository, for_user: User,new_name: str = None):
        data_dict = {'namespace_path':for_user.username}
        if new_name:
            data_dict["name"] = new_name
            data_dict["path"] = new_name
        async with self._http.post(f"/api/v4/projects/{repo.git_service_id}/fork",data=data_dict) as r:
            if not (r.status >= 200 and r.status < 300):
                raise GitlabServiceError(await r.text())

    async def get_all_repositories(self) -> List[Repository]:

        repos: List[Repository] = []

        async for repo_data in pagination_iter(self._http,'/api/v4/projects'):
            repos.extend(
            filter(
                lambda e: e is not None,
                map(transform_repository_data,repo_data) # type: ignore
            )
        )
        return repos

    async def get_user(self, id: Any) -> User:
        async with self._http.get(f"/api/v4/users/{id}") as r:
            if r.status != 200:
                raise GitlabServiceError(await r.text())

            resp = await r.json()
            user = transform_user_data(resp)
            if not user:
                raise GitlabServiceError("Invalid user")
            return user

    async def get_all_users(self) -> List[User]:
        async with self._http.get(f"/api/v4/users?per_page=100") as r:
            if r.status != 200:
                raise GitlabServiceError(await r.text())

            resp: list = await r.json()
            return list(
                filter(
                    lambda e:e is not None,
                    map(transform_user_data,resp) # type: ignore
                )
            )

    async def close(self):
        await self._http.close()



async def pagination_iter(
    session: ClientSession,
    path: str,
    per_page: int = 100,
    from_page: int = 1,
    to_page: int = -1
):
    resp = await session.get(f"{path}?per_page={per_page}&page={from_page}")
    if resp.status != 200:
        raise GitlabServiceError(await resp.text())
    total_pages = int(resp.headers.get('x-total-pages'))
    if to_page == -1 or to_page > total_pages:
        to_page = total_pages

    yield await resp.json()
    resp.release()
    for page in range(from_page+1,to_page+1):
        resp = await session.get(f"{path}?per_page={per_page}&page={page}")
        if resp.status != 200:
            raise GitlabServiceError(await resp.text())
        yield await resp.json()
        resp.release()


def transform_user_data(user_data: Any) -> Union[User,None]:
    auth0_id = None
    for id in user_data["identities"]:
        if id["provider"] == "openid_connect":
            auth0_id = id["extern_uid"]
            break
    if not auth0_id: # we don't care about users without auth0 id
        return None
    return User(
        auth_id=auth0_id,
        email=user_data["email"],
        username=user_data["username"],
        git_service_id=user_data["id"]
    )


def transform_repository_data(repo_data: Any) -> Union[Repository,None]:
    if not ("owner" in repo_data): # we don't deal with repos without owner
        return None
    return Repository(
        git_service_id=repo_data["id"],
        default_branch=repo_data["default_branch"],
        http_url=repo_data["http_url_to_repo"],
        name=repo_data["path"],
        owner_id=repo_data["owner"]["id"],
        owner_name=repo_data["owner"]["username"],
        forked_from_id=repo_data["forked_from_project"]["id"] if "forked_from_project" in repo_data else None,
        imported_from=repo_data["description"] or None
    )


#TODO: API call to update git service users