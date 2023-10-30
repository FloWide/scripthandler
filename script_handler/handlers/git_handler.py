from typing import Dict, List,Optional
from fastapi import APIRouter, Request,HTTPException, Response
import pygit2 as git

from ..models.base_model import BaseModel

from ..models.repository import Repository

from .utils import api_route,HandlerClass

class BranchCreationModel(BaseModel):
    name: str

class TagCreationModel(BaseModel):
    name: str
    message: Optional[str] = ''
    auto_push: Optional[bool] = True

class GitCompoundStateResponseModel(BaseModel):
    head: str
    tags: List[str]
    branches: List[str]
    status: Dict[str,int]
    stash_length: int

class GitGetTagsResponseModelListElement(BaseModel):
    name: str
    time: int
    commit: str

class GitCommitRequestModel(BaseModel):
    message: str
    auto_add_file: Optional[bool] = True
    auto_push: Optional[bool] = True

class GitPushRequestModel(BaseModel):
    push_tags: Optional[bool] = True

class GitAddRemoveIndex(BaseModel):
    files: Optional[List[str]]
    all: Optional[bool] = True

class GitRevertFilesRequest(BaseModel):
    files: List[str]

class GitHandler(HandlerClass):


    def __init__(self) -> None:
        self._router = APIRouter(
            redirect_slashes=False,
            tags=["Git"]
        )   
    
    @api_route('',methods=["GET"],response_model=GitCompoundStateResponseModel)
    def get_compound_state(self,request: Request):
        repo: Repository = request.state.repo
        return {
            "head":repo.git_get_head_shorthand(),
            "tags":list(
              map(
                lambda e: e.name.removeprefix('refs/tags/'),
                repo.git_get_tags()
              )  
            ),
            "branches":repo.git_get_branches(),
            "status":repo.git_status(),
            "stash_length":repo.git_get_stashes_length()
        }

    @api_route('/head',methods=["GET"],response_model=str)
    def get_head(self,request: Request):
        repo: Repository = request.state.repo
        return repo.git_get_head_shorthand()

    @api_route('/branches',methods=["GET"],response_model=List[str])
    def get_branches(self,request: Request):
        repo: Repository = request.state.repo
        return repo.git_get_branches()
    
    @api_route('/commits',methods=["GET"],response_model=List[dict])
    def commits(self,request: Request):
        repo: Repository = request.state.repo
        return repo.git_list_commits()

    @api_route('/tags',methods=["GET"],response_model=List[GitGetTagsResponseModelListElement])
    def get_tags(self,request: Request):
        repo: Repository = request.state.repo
        return list(
            map(
                lambda r: {
                    "name": r.name.removeprefix('refs/tags/'),
                    "time": r.peel(git.GIT_OBJ_COMMIT).commit_time,
                    "commit": str(r.peel(git.GIT_OBJ_COMMIT).hex)
                },
                repo.git_get_tags()
            )
        )

    @api_route('/status',methods=["GET"],response_model=Dict[str,int])
    def get_git_status(self,request: Request):
        repo: Repository = request.state.repo
        return repo.git_status()

    @api_route('/create_branch',methods=["POST"],status_code=201)
    def create_branch(self,request: Request,data: BranchCreationModel):
        repo: Repository = request.state.repo
        try:
            repo.git_create_branch(data.name)
        except Exception as e:
            raise HTTPException(400,str(e))

    @api_route('/create_tag',methods=["POST"],status_code=201)
    def create_tag(self,request: Request,data: TagCreationModel):
        repo: Repository = request.state.repo
        try:
            repo.git_tag(data.name,request.user.signature,data.message)
            if data.auto_push:
                repo.git_push(push_tags=True)
        except Exception as e:
            raise HTTPException(400,str(e))

    @api_route('/stash_length',methods=["GET"],response_model=int)
    def get_stash_length(self,request: Request):
        repo: Repository = request.state.repo
        return repo.git_get_stashes_length()

    @api_route('/stash_push',methods=["POST"],status_code=201,response_model=Dict[str,int])
    def stash_push(self,request: Request):
        repo: Repository = request.state.repo
        repo.git_stash(request.user.signature)
        return repo.git_status()

    @api_route('/stash_pop',methods=["POST"],status_code=201,response_model=int)
    def stash_pop(self,request: Request):
        repo: Repository = request.state.repo
        repo.git_stash_pop()
        return repo.git_status()

    @api_route('/commit',methods=["POST"],status_code=204)
    def commit(self,request: Request,data: GitCommitRequestModel):
        repo: Repository = request.state.repo
        try:
            if data.auto_add_file:
                repo.git_add_all()
        
            repo.git_commit(request.user.signature,data.message)
            if data.auto_push:
                repo.git_push()
        except Exception as e:
            raise HTTPException(400,str(e))
        return Response(status_code=204)

    @api_route('/push',methods=["POST"],status_code=204)
    def push(self,request: Request,data: GitPushRequestModel):
        repo: Repository = request.state.repo
        try:
            repo.git_push(push_tags=data.push_tags)
        except Exception as e:
            raise HTTPException(400,str(e))
        return Response(status_code=204)

    @api_route('/add',methods=["POST"],status_code=201,response_model=Dict[str,int])
    def git_add(self,request: Request,data: GitAddRemoveIndex):
        repo: Repository = request.state.repo
        if data.all:
            repo.git_add_all()
            return repo.git_status()

        if not data.files:
            raise HTTPException(400,"Files must be provided if 'all' is not set")

        repo.git_add(data.files)
        return repo.git_status()

    @api_route('/remove',methods=["POST"],status_code=201,response_model=Dict[str,int])
    def git_remove(self,request: Request, data: GitAddRemoveIndex):
        repo: Repository = request.state.repo
        if data.all:
            repo.git_remove_all()
            return repo.git_status()

        if not data.files:
            raise HTTPException(400,"Files must be provided if 'all' is not set")

        repo.git_remove(data.files)
        return repo.git_status()

    @api_route('/revert_files',methods=["POST"],status_code=201,response_model=Dict[str,int])
    def revert_files(self,request: Request,data: GitRevertFilesRequest):
        repo: Repository = request.state.repo
        repo.git_revert_files(data.files)
        return repo.git_status()

    @property
    def router(self):
        return self._router
