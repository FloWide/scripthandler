


from enum import Enum
from optparse import Option
import shutil
from typing import Dict, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException,Request, Response

from fastapi.responses import FileResponse,RedirectResponse

from script_handler.models.app_config import AppType, MetaData

from .edit_handler import EditHandler
from .git_handler import GitHandler
from ..runner.runner_factory import RunnerFactory

from ..git.git_repository import GitAnalyzeResults, GitRepository

from ..git.git_service_provider import GitServiceProvider
from ..models.base_model import BaseModel
from ..models.repository import Repository,RepositoryModel

from ..models.user import User
from ..models.collections import RepositoryCollection, UserCollection

from .gitlab_hook_handler import GitlabHookHandler
from .utils import api_route,HandlerClass
from starlette.authentication import requires
import os
from distutils import dir_util
from pathlib import Path
import hashlib
import pygit2

TEMPLATES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),'..','templates'))


class RepositoryTemplates(str,Enum):
    PYTHON = 'python'
    SERVICE = 'service'
    STREAMLIT = 'streamlit'

class CheckUpdateResponseModel(BaseModel):
    status: GitAnalyzeResults

class UpdateRequestModel(BaseModel):
    auto_merge: Optional[bool]
    force_update: Optional[bool]
    leave_merge_conflict: Optional[bool]

class RepositoryCreationModel(BaseModel):
    name: str
    template: Optional[RepositoryTemplates]

class RepositoryImportModel(RepositoryCreationModel):
    from_url: str
    oauth_token: Optional[str] = ""
    ref: Optional[str]

class RepositoryForkModel(BaseModel):
    new_name: Optional[str]
    to_user_id: int

class RepositoryHandler(HandlerClass):

    def __init__(
        self,
        repo_collection: RepositoryCollection,
        user_collection: UserCollection,
        git_service: GitServiceProvider,
        runner_factory: RunnerFactory,
        venv_activator: str,
        enable_lsp: bool,
        gitlab_hook_handler: GitlabHookHandler
    ) -> None:
        self._repo_collection = repo_collection
        self._user_collection = user_collection
        self._git_service = git_service
        self._gitlab_hook_handler = gitlab_hook_handler
        self._router = APIRouter(
            prefix="/repo",
            redirect_slashes=False,
            tags=["Repository"],
            dependencies=[Depends(self._repo_by_id)]
        )
        edit_handler = EditHandler(self._repo_collection,runner_factory,venv_activator,enable_lsp)
        self._router.include_router(router=edit_handler.router,prefix='/{id}/edit',dependencies=[Depends(self._repo_by_id)])
        git_handler = GitHandler()
        self._router.include_router(router=git_handler.router,prefix='/{id}/git',dependencies=[Depends(self._repo_by_id)])

    @api_route('',methods=["GET"],response_model=Dict[str,RepositoryModel])
    def get_repos(self,request: Request):
        user: User = request.user
        return self._repo_collection.get_user_repos(user)

    @api_route('/{id}',methods=["GET"],response_model=RepositoryModel)
    def get_repo(self,request: Request):
        return request.state.repo

    @requires(["create:repo"])
    @api_route('',methods=["POST"],status_code=201,response_model=RepositoryModel)
    async def create_repo(self,request: Request,creation: RepositoryCreationModel):
        repo = await self._git_service.create_repository(request.user,creation.name)
        try:
            if creation.template:
                template_path = os.path.join(TEMPLATES_ROOT,creation.template)
                dir_util.copy_tree(template_path,repo.get_root_path())
                config = Path( os.path.join(repo.get_root_path(),'appconfig.yml') )
                text = config.read_text()
                text = text.replace("%repo-name%",repo.name)
                config.write_text(text)
                repo.git_add_all()
                repo.git_commit(message=f"Created from {creation.template} template")
                repo.git_push()
                await repo.update_app_config()
            self._repo_collection.new_repo(repo)
        except Exception as e:
            repo.delete_local_repository()
            await self._git_service.delete_repository(repo)
            raise HTTPException(status_code=500,detail=str(e))
        return repo

    @api_route('/{id}',methods=["DELETE"],status_code=204)
    async def delete_repo(self,request: Request):
        repo: Repository = request.state.repo
        
        await self._git_service.delete_repository(repo)
        repo.delete_local_repository()
        self._repo_collection.delete_repo(repo)
        return Response(status_code=204)

    @requires(['fork:repo'])
    @api_route('/{id}/fork',methods=["POST"])
    async def fork_repo(self,request: Request,fork_data: RepositoryForkModel):
        repo: Repository = request.state.repo
    
        to_user = self._user_collection.get_user_by_git_id(fork_data.to_user_id)
        if not to_user:
            raise HTTPException(400,"Fork target user does not exists")
        
        await self._git_service.fork_repository(
            repo,
            to_user,
            fork_data.new_name if hasattr(fork_data,'new_name') else None
        )
        return Response(status_code=202)

    @api_route('/{id}/checkupdate',methods=["GET"],response_model=CheckUpdateResponseModel)
    async def check_update(self,request: Request):
        repo: Repository = request.state.repo

        if not repo.git_has_remote("upstream"):
            raise HTTPException(400,"Repository was not forked")

        return {
            "status":repo.git_remote_analyze("upstream")
        }


    @api_route('/{id}/update',methods=["POST"],response_model=CheckUpdateResponseModel)
    async def update(self,request: Request,id: int,params: Optional[UpdateRequestModel] = None):
        repo: Repository = request.state.repo

        if not repo.git_has_remote("upstream"):
            raise HTTPException(400,"Repository was not forked")

        analysis_result = repo.git_remote_analyze('upstream')

        if analysis_result == GitAnalyzeResults.UP_TO_DATE:
            return {
                "status":GitAnalyzeResults.UP_TO_DATE
            }
        elif analysis_result == GitAnalyzeResults.FAST_FORWARD:
            repo.git_pull('upstream')
            await repo.on_update()
            return {
                "status":GitAnalyzeResults.FAST_FORWARD
            }
        elif analysis_result == GitAnalyzeResults.MERGE_REQUIRED:
            if not params or not params.auto_merge:
                raise HTTPException(400,"Merging is required, but auto_merge argument is not set. Aborting")

            pull_results = repo.git_pull("upstream",not params.leave_merge_conflict)
            if pull_results == GitAnalyzeResults.AUTO_MERGE:
                await repo.on_update()
                return {
                    "status":GitAnalyzeResults.AUTO_MERGE
                }
            elif pull_results == GitAnalyzeResults.MERGE_CONFLICT_LOCAL_HARD_RESET:
                if not params or not params.force_update:
                    raise HTTPException(400,"Merge conflict occured but no force update was set! Reseting to HEAD")
                
                fork_source = self._repo_collection.get_repo_by_id(repo.forked_from_id)
                owner = self._user_collection.get_user_by_git_id(repo.owner_id)
                await self._git_service.delete_repository(repo)
                repo.delete_local_repository()
                await self._git_service.fork_repository(fork_source,owner,repo.name) # type: ignore
                return {
                    "status":GitAnalyzeResults.MERGE_CONFLICT_REMOTE_HARD_RESET
                }
            elif pull_results == GitAnalyzeResults.MERGE_CONFLICT:
                return {
                    "status":GitAnalyzeResults.MERGE_CONFLICT
                }

        raise HTTPException(500,"Unknown merge analysis results")

    @requires(['create:release'])
    @api_route('/{id}/create_release',methods=["POST"])
    async def create_release(self,request: Request,tag_name: str,commit_sha: Optional[str] = None):
        repo: Repository = request.state.repo
        user: User = request.user
        try:
            await repo.update_app_config()
        except Exception as e:
            raise HTTPException(status_code=500,detail="Invalid appconfig.yml")

        for name,app in repo.apps_config.apps.items():
            if app.type == AppType.STREAMLIT or app.type == AppType.PYTHON:
                if not self._repo_collection.scripts.is_name_available(name,repo):
                    raise HTTPException(status_code=500,detail=f"Script with {name} already exists")
            elif app.type == AppType.SERVICE:
                if not self._repo_collection.services.is_name_available(name,repo):
                    raise HTTPException(status_code=500,detail=f"Service with {name} already exists")
        commit = None
        if commit_sha:
            try:
                commit = repo._git_repo.revparse_single(commit_sha)
            except KeyError:
                raise HTTPException(400,f"Commit with sha {commit_sha} not found")
        if commit:
            tag = repo.git_tag(tag_name,user.signature,commit_oid=commit.oid)
        else:
            tag = repo.git_tag(tag_name,user.signature)
        repo.git_push(push_tags=True)
        repo.new_release(tag)
        return True

    @requires(['create:release'])
    @api_route('/{id}/delete_release',methods=["DELETE"])
    async def delete_release(self,request: Request,tag_name: str):
        repo: Repository = request.state.repo
        release = repo.releases.get_release(tag_name)
        if not release:
            raise HTTPException(status_code=404,detail=f"Not found release with tag {tag_name}")
        repo.delete_release(release) 
        repo.git_push(push_tags=True)
        return True

    @requires(["create:repo"])
    @api_route('/import',methods=["POST"],response_model=RepositoryModel)
    async def import_from_git(self,request: Request,creation: RepositoryImportModel):
        self._gitlab_hook_handler.ignore_list.add(creation.name)
        try:
            bare_repo = await self._git_service.create_raw_repository(request.user,creation.name,description=creation.from_url)
        except Exception as e:
            self._gitlab_hook_handler.ignore_list.remove(creation.name)
            raise HTTPException(detail=str(e))
        try:
            temp_folder = f'/tmp/{hashlib.md5(creation.from_url.encode()).hexdigest()}'
            if os.path.exists(temp_folder):
                shutil.rmtree(temp_folder)
            git_repo = pygit2.clone_repository(
                creation.from_url,
                temp_folder,
                callbacks=pygit2.RemoteCallbacks(
                    pygit2.UserPass("x-access-token",creation.oauth_token)
                )
            )
            git_repo.create_remote('gitlab',bare_repo["http_url_to_repo"])
            if not creation.ref:
                creation.ref = git_repo.head.name
            try:
                commit: pygit2.Commit
                ref: pygit2.Reference
                commit,ref = git_repo.resolve_refish(creation.ref)
            except pygit2.GitError:
                raise HTTPException(400,f"Invalid ref name {creation.ref}")

            push_tag = ref.name.startswith('refs/tags/') and not ref.name.lower().endswith('uc')
            git_repo.head.set_target(commit.id)
            git_repo.remotes['gitlab'].push(
                [
                    git_repo.head.name,
                ],
                callbacks=GitRepository.git_remote_callbacks
            )
            if push_tag:
                git_repo.remotes["gitlab"].push([ref.name],callbacks=GitRepository.git_remote_callbacks)

            repo = Repository(
                git_service_id=bare_repo["id"],
                default_branch=bare_repo["default_branch"],
                http_url=bare_repo["http_url_to_repo"],
                name=bare_repo["path"],
                owner_id=bare_repo["owner"]["id"],
                owner_name=bare_repo["owner"]["username"],
                forked_from_id=bare_repo["forked_from_project"]["id"] if "forked_from_project" in bare_repo else None,
                imported_from=bare_repo["description"] or None
            )
            await repo.update_app_config()
            self._repo_collection.new_repo(repo)
            self._gitlab_hook_handler.ignore_list.remove(creation.name)
            return repo
        except Exception as e:
            if bare_repo:
                await self._git_service.delete_repository_by_id(bare_repo["id"])
            self._gitlab_hook_handler.ignore_list.remove(creation.name)
            raise HTTPException(500,str(e))
        

    def _repo_by_id(self,request: Request,id: Optional[int] = None):
        if id is None:
            return

        repo = (self._repo_collection.get_user_repos(request.user) or {}).get(id)

        if not repo:
            raise HTTPException(404,"Repository not found")
        request.state.repo = repo


    @property
    def router(self):
        return self._router