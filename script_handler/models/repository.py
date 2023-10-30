

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Awaitable, Callable, List, Literal, Optional, Union
import os
import base64
import aiofiles
import shutil
from fastapi import WebSocket
from pydantic import ValidationError,validator
import pygit2 as git

from script_handler.models.releases import Release, Releases

from .app_config import AppConfig, AppConfigsJson, AppType, RuntimeConfig
from ..git.git_repository import GitAnalyzeResults, GitRepository
from .base_model import BaseModel
import glob
import json
import yaml

class RepositoryFileEntry(BaseModel):
    name: str
    path: str
    type: Union[Literal["file"],Literal["folder"]]
    children: Optional[List["RepositoryFileEntry"]]

RepositoryFileEntry.update_forward_refs()

class RepositoryEditor:

    _local_root_path: str

    _editing_ws: Optional["EditWebsocketHandler"] # type: ignore

    def move_file(self,from_path: str,to_path: str):
        from_path = os.path.join(self._local_root_path,from_path)
        to_path = os.path.join(self._local_root_path,to_path)

        if not os.path.exists(os.path.dirname(to_path)):
            os.makedirs(os.path.dirname(to_path),exist_ok=True)

        os.rename(from_path,to_path)

    async def update_file(self,file: str,content: Union[str,bytes], base64encoded: bool = False):
        if base64encoded:
            content = base64.b64decode(content)

        file = os.path.join(self._local_root_path,file)

        async with aiofiles.open(file,'w' if not base64encoded else 'wb') as f: # type: ignore
            await f.write(content)

    def update_file_blocking(self,file: str,content: Union[str,bytes], base64encoded: bool = False):
        if base64encoded:
            content = base64.b64decode(content)

        file = os.path.join(self._local_root_path,file)

        with open(file,'w' if not base64encoded else 'wb') as f: # type: ignore
            f.write(content)

    async def create_file(self,file: str, content: Union[str,bytes],base64encoded: bool = False):
        if content and base64encoded:
            content = base64.b64decode(content)

        file = os.path.join(self._local_root_path,file)
        if not os.path.exists(os.path.dirname(file)):
            os.makedirs(os.path.dirname(file),exist_ok=True)

        if not content:
            open(file,'a').close()
        else:
            async with aiofiles.open(file,'w' if not base64encoded else 'wb') as f: # type: ignore
                await f.write(content)

    def create_file_blocking(self,file: str,content: Union[str,bytes],base64encoded: bool = False):
        if content and base64encoded:
            content = base64.b64decode(content)

        file = os.path.join(self._local_root_path,file)
        if not os.path.exists(os.path.dirname(file)):
            os.makedirs(os.path.dirname(file),exist_ok=True)

        if not content:
            open(file,'a').close()
        else:
            with open(file,'w' if not base64encoded else 'wb') as f: # type: ignore
                f.write(content)

    def delete(self,path: str):
        path = os.path.join(self._local_root_path,path)

        if os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)

    def delete_local_repository(self):
        shutil.rmtree(self._local_root_path)

    def clean_local_repository(self):
        """Deletes every file from the local repository"""
        for path in glob.glob(f"{self._local_root_path}/*"):
            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)

    async def get_file_content(self,path: str):
        path = os.path.join(self._local_root_path,path)

        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} doesn't exist")

        async with aiofiles.open(path,'r') as f:
            return await f.read()

    def get_file_content_blocking(self,path: str):
        path = os.path.join(self._local_root_path,path)

        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} doesn't exist")

        with open(path,'r') as f:
            return f.read()

    def get_file_tree(self) -> List[RepositoryFileEntry]:
        return self.dir_to_list(self._local_root_path)
    
    def dir_to_list(self,root,path="") -> list:
        data = []
        for name in os.listdir(root):
            full_path = os.path.join(root, name)
            if name.startswith(".git") and os.path.isdir(full_path):
                 continue

            dct = {}
            dct['name'] = name
            dct['path'] = path + name

            
            if os.path.isfile(full_path):
                dct['type'] = 'file'
            elif os.path.isdir(full_path):
                dct['type'] = 'folder'
                dct['children'] = self.dir_to_list(full_path, path=path + name + os.path.sep)
            data.append(dct)
        return data

    # @property decarotor not working with pydantic models
    def set_edit_ws(self,ws: Optional["EditWebsocketHandler"]): # type: ignore
        self._editing_ws = ws

    def get_edit_ws(self) -> Optional["EditWebsocketHandler"]: # type: ignore
        return self._editing_ws

    def get_root_path(self) -> str:
        return self._local_root_path

DEFAULT_APP_CONFIG = AppConfig(
            app_icon='',
            type=AppType.STREAMLIT,
            config=RuntimeConfig(
                entry_file="main.py",
                env={},
                cli_args=[]
            ),
)

class RepositoryModel(BaseModel):
    git_service_id: int
    http_url: str
    name: str
    default_branch: str
    owner_id: int
    owner_name: str
    root_path: Optional[str] = None
    forked_from_id: Optional[int] = None
    imported_from: Optional[str] = None

    apps_config: AppConfigsJson = None

class Repository(
    RepositoryModel,
    GitRepository,
    RepositoryEditor
):

    git_service_id: int
    http_url: str
    name: str
    default_branch: str
    owner_id: int
    owner_name: str
    root_path: Optional[str] = None
    forked_from_id: Optional[int] = None
    imported_from: Optional[str] = None

    apps_config: AppConfigsJson = None

    _repos_root: str

    _local_root_path: str
    _git_repo: git.Repository

    _editing_ws: Optional[WebSocket]

    _releases: Releases

    def __init__(
        self,
        **kwargs
    ) -> None:
        super(Repository,self).__init__(**kwargs)
        self._local_root_path = os.path.join(Repository._repos_root,self.owner_name,self.name)
        self.root_path = self._local_root_path

        if os.path.exists(self._local_root_path):
            self._git_repo = GitRepository.git_discover_repository(self._local_root_path)
            analyze = self.git_remote_analyze()
            if analyze != GitAnalyzeResults.UP_TO_DATE:
                if self.git_status():
                    self.git_stash(git.Signature("API","api@flowide.net"))
                pull_results = self.git_pull()
                if pull_results == GitAnalyzeResults.MERGE_CONFLICT_LOCAL_HARD_RESET:
                    logging.warning(f"Couldn't update pull changes repository for repository {self.name}. Merge conflict occured!")
        else:
            self._git_repo = GitRepository.git_clone(self.http_url,self._local_root_path)
            self.ensure_root_commit()

        self._editing_ws = None
        self._load_app_config()

        
        self._releases = Releases(self,[])
        for tag in self.git_get_tags():
            self.new_release(tag)


    @classmethod
    def set_repos_root(cls,path: str):
        cls._repos_root = path  

    def _load_app_config(self):
        path = os.path.join(self._local_root_path,'appconfig.yml')

        if not os.path.exists(path):
            self.apps_config = AppConfigsJson(apps={
                self.name:DEFAULT_APP_CONFIG
            })
            self.create_file_blocking('appconfig.yml',dumb_yaml_dump(self.apps_config.dict()))
            self.git_add_all()
            self.git_commit(git.Signature("API","api@flowide.net"),"Creating appconfig.yml")
            self.git_push()
            return

        try:
            config_file_content = yaml.full_load(self.get_file_content_blocking('appconfig.yml'))
            self.apps_config = AppConfigsJson.parse_obj(config_file_content)
        except (ValidationError,yaml.error.YAMLError) as e: # file is invalid use default config
            logging.warning(e)
            self.apps_config = AppConfigsJson(apps={
                self.name:DEFAULT_APP_CONFIG
            })
            self.write_app_config_blocking()
            logging.info(f"Overriding to default appconfig.yml for {self.name} repo")

    async def update_app_config(self):
        try:
            self.apps_config = AppConfigsJson.parse_obj(yaml.full_load(
                await self.get_file_content("appconfig.yml")
            ))
        except (FileNotFoundError,ValidationError,yaml.error.YAMLError):
            self.apps_config = AppConfigsJson(apps={
                self.name:DEFAULT_APP_CONFIG
            })

    async def write_app_config(self):
        await self.update_file('appconfig.yml',dumb_yaml_dump(self.apps_config.dict()))
        self.git_add("appconfig.yml")
        self.git_commit(git.Signature("API","api@flowide.net"),"Updating appconfig.yml")
        self.git_push()

    def write_app_config_blocking(self):
        self.update_file_blocking('appconfig.yml',dumb_yaml_dump(self.apps_config.dict()))
        self.git_add("appconfig.yml")
        self.git_commit(git.Signature("API","api@flowide.net"),"Updating appconfig.yml")
        self.git_push()


    def new_release(self,tag: git.Reference):
        if tag.name.lower().endswith('uc'):
            logging.info(f"Ignoring tag {tag.name} for new release because it's unconfigured")
            return
        commit = tag.peel(git.GIT_OBJ_COMMIT)
        try:
            release_apps_config = AppConfigsJson.parse_obj(
                yaml.full_load(self.git_get_tagged_file(tag.name.removeprefix('refs/tags/'),"appconfig.yml"))
            )
            self._releases.new_release(
                Release(self,tag.name.removeprefix('refs/tags/'),release_apps_config.apps,commit.commit_time)
            )
        except Exception as e:
            logging.error(e)
            logging.info(f"Deleting tag: {tag.name} for {self.name}")
            self.git_delete_tag(tag.name.removeprefix('refs/tags/'))

    def delete_release(self,release: Release):
        self._releases.delete_release(release)
        self.git_delete_tag(release.tag_name)
    
    async def on_update(self):
        for tag in self.git_get_tags():
            self.new_release(tag)
        try:
            self.git_push(push_tags=True)
        except Exception as e:
            logging.warning(e)

    @property
    def releases(self):
        return self._releases
    

def dumb_yaml_dump(data: dict):
    # pyyaml dumps python objects with tags ruining the yaml format
    # this way these tags won't be created and only simple strings will be dumped
    return yaml.dump(json.loads(json.dumps(data)),default_flow_style=False)