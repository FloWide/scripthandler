import logging
from fastapi import APIRouter, Depends,Request,Response,HTTPException

from script_handler.git.git_service_provider import GitServiceProvider
from script_handler.git.gitlab_service import GitlabServiceError
from .utils import HandlerClass,api_route
from ..models.collections import RepositoryCollection, UserCollection
from typing import Set, Union

class GitlabHookHandler(HandlerClass):

    def __init__(
        self,
        repos: RepositoryCollection,
        users: UserCollection,
        git_service: GitServiceProvider,
        secret: str
    ) -> None:
        self._repos = repos
        self._users = users
        self._git_service = git_service
        self._secret = secret
        self._ignore_list: Set[Union[int,str]] = set()
        self._router = APIRouter(
            dependencies=[Depends(self._check_secret)],
            tags=["Gitlab hook"],
            prefix='/gitlab'
        )

    @api_route('/hook',methods=["POST"])
    async def hook_entry(self,request: Request):
        try:
            body: dict = await request.json()
        except:
            return Response(status_code=400)

        if body.get('project_id') in self.ignore_list or body.get('path') in self.ignore_list:
            logging.debug(f"Ignoring hook message because it was found in ignore list:  {body.get('project_id')} / {body.get('path')}")
            return

        event = body.get('event_name')
        if event == 'project_create':
            await self.on_project_create(body)
        elif event == 'project_destroy':
            await self.on_project_remove(body)
        elif event == 'user_create':
            await self.on_user_create(body)
        elif event == 'user_destroy':
            await self.on_user_remove(body)
        elif event == 'tag_push':
            await self.on_tag_push(body)
        else:
            logging.info(f"Unhandled gitlab hook event: {event}")

        return Response(status_code=201)

    async def on_project_create(self,details: dict):
        project_id = details.get('project_id')
        if not project_id:
            return
        try:
            repo = await self._git_service.get_repository_by_id(project_id)
            self._repos.new_repo(repo)
        except GitlabServiceError as e:
            logging.warn(f"Failed to get repository in hook: {e}")
        

    async def on_project_remove(self,details: dict):
        project_id = details.get('project_id')
        if not project_id:
            return
        repo = self._repos.get_repo_by_id(project_id)
        if repo:
            self._repos.delete_repo(repo)

    async def on_user_create(self,details: dict):
        user_id = details.get('user_id')
        if not user_id:
            return
        try:
            user = await self._git_service.get_user(user_id)
            self._users.new_user(user)
        except GitlabServiceError as e:
            logging.warn(f"Failed to get user in hook {e}")


    async def on_user_remove(self,details: dict):
        user_id = details.get('user_id')
        if not user_id:
            return
        user = self._users.get_user_by_git_id(user_id)
        if user:
            self._users.delete_user(user)

    async def on_tag_push(self,details: dict):
        repo_id = details["project_id"]
        repo = self._repos.get_repo_by_id(repo_id)
        ref: str = details["ref"]
        is_delete = details["after"].startswith("0000000000")
        repo.git_pull()
        if is_delete:
            tag_name = ref.removeprefix("refs/tags/")
            release = repo.releases.get_release(tag_name)
            if release:
                repo.delete_release(release)
        else:
            tags = repo.git_get_tags()
            for tag in tags:
                if tag.name == ref:
                    repo.new_release(tag)

    @property
    def ignore_list(self):
        return self._ignore_list

    def _check_secret(self,request: Request):
        secret = request.headers.get('x-gitlab-token')
        if secret != self._secret:
            raise HTTPException(status_code=403,detail="Invalid secret")

    @property
    def router(self) -> APIRouter:
        return self._router