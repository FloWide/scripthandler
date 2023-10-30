import shutil
from typing import Callable, Dict, List
import os

from .app_config import AppConfig

class Release:

    _root_path: str = '/tmp'

    def __init__(
        self,
        repo: "Repository", # type: ignore
        tag_name: str,
        apps: Dict[str,AppConfig],
        time: int = None,
        shared_owner_id = None
    ) -> None:
        self.repo = repo
        self.tag_name = tag_name
        self.time = time
        self._shared_owner_id = shared_owner_id
        self._path = os.path.join(
            self._root_path,(str(self._shared_owner_id) if self._shared_owner_id is not None else str(self.repo.owner_id)),repo.name,tag_name
        )
        
        self._apps = apps
        self.load()

    def load(self):
        if self.loaded_on_disk:
            return
        self.repo.git_copy_tagged_version(self.tag_name,self._path)

    def unload(self):
        shutil.rmtree(self.root_path)

    @property
    def root_path(self):
        return self._path

    @property
    def apps(self):
        return self._apps

    @property
    def loaded_on_disk(self):
        return os.path.exists(self._path)

    @property
    def id(self):
        return self.tag_name

    @property
    def owner_id(self):
        return self.repo.owner_id

    @property
    def shared_to_id(self):
        return self._shared_owner_id

    @classmethod
    def set_root_path(cls,path: str):
        cls._root_path = path


    def clone_to_shared(self,shared_owner_id):
        return Release(
            self.repo,
            self.tag_name,
            self.apps,
            self.time,
            shared_owner_id
        )




HookFunction = Callable[["Repository",Release],None] # type: ignore

class Releases:

    def __init__(
        self,
        repo: "Repository", # type: ignore
        releases: List[Release]
    ) -> None:
        self._releases: Dict[str,Release] = {}
        self._repo = repo
        self._new_hooks: List[HookFunction] = []
        self._delete_hooks: List[HookFunction] = []
        for r in releases:
            self.new_release(r)


    def new_release(self,rel:Release):
        if rel.tag_name in self._releases:
            return
        
        self._releases[rel.tag_name] = rel

        for hook in self._new_hooks:
            hook(self._repo,rel)

    def delete_release(self,rel: Release):
        if rel.tag_name not in self._releases:
            return        
        del self._releases[rel.tag_name]
        for hook in self._delete_hooks:
            hook(self._repo,rel)
        rel.unload()


    def get_release(self,tag_name: str) -> Release | None:
        return self._releases.get(tag_name)

    def add_new_hook(self,fn: HookFunction):
        self._new_hooks.append(fn)
    
    def add_delete_hook(self,fn: HookFunction):
        self._delete_hooks.append(fn)

    @property
    def releases(self) -> List[str]:
        return list(self._releases.keys())
   
    def __iter__(self):
        for key,r in self._releases.items():
            yield r