


import asyncio
from typing import Any, Dict, List, Optional, Set,Union,Protocol,TypeVar,Generic
from .releases import Release

from script_handler.runner.subprocess_runner import StreamStrategy
from .app_config import AppType

from ..runner.runner_factory import RunnerFactory

from .script import Script
from .user import User
from .repository import Repository
from .service import Service

from fastapi.requests import Request

import logging
import itertools

class UserCollection:

    def __init__(self,users: List[User]) -> None:
        self._users_by_git_id: Dict[Any,User] = {}
        self._users_by_auth_id: Dict[Any,User] = {}
        for user in users:
            self.new_user(user)

    @property
    def users(self):
        return self._users_by_git_id

    def get_user_by_git_id(self,id: Any) -> Optional[User]:
        return self._users_by_git_id.get(id)

    def get_user_by_auth_id(self,id: Any) -> Optional[User]:
        return self._users_by_auth_id.get(id)

    def get_user_by_username(self,username: str) -> Optional[User]:
        for key,user in self._users_by_git_id.items():
            if user.username == username:
                return user
        return None

    def new_user(self,u: User):
        if u.git_service_id in self._users_by_git_id.keys():
            return
        self._users_by_auth_id[u.auth_id] = u
        self._users_by_git_id[u.git_service_id] = u
        logging.info(f"New user added: {u}")

    def delete_user(self,u: User):
        del self._users_by_auth_id[u.auth_id]
        del self._users_by_git_id[u.git_service_id]
        logging.info(f"User deleted: {u}")

    def __repr__(self) -> str:
        return "{}[\n{}\n]".format(type(self).__name__, "\n".join(map(lambda e:str(e),self._users_by_git_id.values())))

class RepositoryCollection:

    def __init__(
        self,
        repos:List[Repository],
        scripts: "ObjCollection[Script]",
        services: "ObjCollection[Service]",
        runner_factory: RunnerFactory
    ) -> None:
        self._repos_by_id: Dict[Any,Repository] = {}
        self._repos_by_name: Dict[str,Repository] = {}
        self._repos_by_owner_id: Dict[Any,Dict[Any,Repository]] = {}        
        self._scripts = scripts
        self._services = services
        self._runner_factory = runner_factory
        for repo in repos:
            self.new_repo(repo)

        self._set_fork_upstream(repos)
        

    def get_repo_by_id(self,id: Any) -> Optional[Repository]:
        return self._repos_by_id.get(id)
    
    def get_repo_by_name(self,name: str) -> Optional[Repository]:
        return self._repos_by_name.get(name)

    def get_user_repos(self,user: Union[User,Any]) -> Optional[Dict[Any,Repository]]:
        if isinstance(user,User):
            return self._repos_by_owner_id.get(user.git_service_id,{})
        else:
            return self._repos_by_owner_id.get(user,{})

    def get_user_repo(self,user: Union[User,Any],repo_id: Any) -> Optional[Repository]:
        user_repos = self.get_user_repos(user)
        if not user_repos:
            return None
        return user_repos.get(repo_id)

    def new_repo(self,repo: Repository):
        if repo.git_service_id in self._repos_by_id.keys():
            return

        
        self._repos_by_id[repo.git_service_id] = repo
        self._repos_by_name[repo.name] = repo
        if repo.owner_id in self._repos_by_owner_id:
            self._repos_by_owner_id[repo.owner_id][repo.git_service_id] = repo
        else:
            self._repos_by_owner_id[repo.owner_id] = {
                repo.git_service_id: repo
            }

        for release in repo.releases:
            self.new_release(repo,release)

        repo.releases.add_new_hook(self.new_release)
        repo.releases.add_delete_hook(self.delete_release)

        logging.info(f"New repository added: {repo}")

    def delete_repo(self,repo: Repository):
        del self._repos_by_id[repo.git_service_id]
        del self._repos_by_name[repo.name]
        if repo.owner_id in self._repos_by_owner_id:
            del self._repos_by_owner_id[repo.owner_id][repo.git_service_id]

        for release in repo.releases:
            self.delete_release(repo,release)

        logging.info(f"Repository deleted: {repo}")
    

    def new_release(self,repo: Repository,release: Release):

        for name,config in release.apps.items():
            if config.type == AppType.PYTHON or config.type == AppType.STREAMLIT:
                self._scripts.new_object(
                    Script(
                        release,
                        name,
                        config,
                        self._runner_factory.create_python_runner(release.root_path) if config.type == AppType.PYTHON else self._runner_factory.create_streamlit_runner(release.root_path)
                    )
                )
            elif config.type == AppType.SERVICE:
                self._services.new_object(
                    Service(
                        release,
                        name,
                        config,
                        self._runner_factory.create_python_runner(release.root_path)
                    )
                )
            else:
                logging.warning(f"Unknown appconfig type: {config.type} in release: {release.tag_name} repository: {repo.git_service_id} appname: {name}")

    def delete_release(self,repo: Repository,release: Release):
        scripts = self._scripts.get_objects_for_release(release)
        services = self._services.get_objects_for_release(release)
        for script in scripts:
            if script.release.repo.git_service_id == repo.git_service_id:
                if script.runner.is_running:
                    asyncio.ensure_future(script.kill())
                self._scripts.delete_object(script)
        for service in services:
            if script.release.repo.git_service_id == repo.git_service_id:
                if service.runner.is_running:
                    asyncio.ensure_future(service.kill())
                self._services.delete_object(service)


    def _set_fork_upstream(self,repos: List[Repository]):
        for repo in repos:
            if repo.forked_from_id:
                fork_origin = self.get_repo_by_id(repo.forked_from_id)
                if fork_origin:
                    repo.git_create_remote('upstream',fork_origin.http_url)
            elif repo.apps_config.metadata and repo.apps_config.metadata.imported_from:
                repo.git_create_remote('upstream',repo.apps_config.metadata.imported_from)


    def __repr__(self) -> str:
        return "{}[\n{}\n]".format(type(self).__name__, "\n".join(map(lambda e:str(e),self._repos_by_id.values())))

    @property
    def scripts(self):
        return self._scripts
    
    @property
    def services(self):
        return self._services


class ReleaseObject(Protocol):
    version: str
    name: str
    release: Release
    def clone_to_shared(self,shared_owner_id):
        ...

T  = TypeVar('T',bound=ReleaseObject)

class ByNameCollection(Generic[T]):

    def __init__(self) -> None:
        super().__init__()
        self._by_name: Dict[str,Dict[str,T]] = {}

    def new_object(self,obj: T):
        if obj.name in self._by_name:
            self._by_name[obj.name][obj.version] = obj
        else:
            self._by_name[obj.name] = {
                obj.version:obj
            }

    def delete_object(self,obj : T):
        if (obj.name not in self._by_name) or (obj.version not in self._by_name[obj.name]):
            return
        del self._by_name[obj.name][obj.version]
        if len(self._by_name[obj.name]) == 0:
            del self._by_name[obj.name]

    def get_all(self):
        return self._by_name

    def get_by_name(self,name: str):
        return self._by_name.get(name,{})

    def get_object(self,name: str,version: str):
        return self.get_by_name(name).get(version)

    def delete_name_entry(self,name: str):
        if not name in self._by_name:
            return
        del self._by_name[name]

    def get_all_for_release(self,release: Release):
        objects = []
        for name,by_version in self._by_name.items():
            for version,obj in by_version.items():
                if version == release.id:
                    objects.append(obj)
        return objects


class ObjCollection(Generic[T]):
    
    def __init__(self,*types: AppType) -> None:
        self._by_name: ByNameCollection[T] = ByNameCollection()
        self._by_owner_id: Dict[int,ByNameCollection[T]] = {}
        self.types = types or tuple()

    def new_object(self, obj : T):
        with_user_id = obj.release.shared_to_id if obj.release.shared_to_id else obj.release.owner_id

        if with_user_id == obj.release.owner_id:
            self._by_name.new_object(obj)

        if with_user_id in self._by_owner_id:
            self._by_owner_id[with_user_id].new_object(obj)
        else:
            self._by_owner_id[with_user_id] = ByNameCollection()
            self._by_owner_id[with_user_id].new_object(obj)

    def delete_object(self,obj: T):
        with_user_id = obj.release.shared_to_id if obj.release.shared_to_id else obj.release.owner_id

        if with_user_id == obj.release.owner_id:
            self._by_name.delete_object(obj)
        self._by_owner_id[with_user_id].delete_object(obj)

    def get_all(self):
        return self._by_name.get_all()

    def get_by_name(self,name: str):
        return self._by_name.get_by_name(name)

    def get_objects(self,name: int,obj_id: str):
        objects: List[T] = []
        for owner_id,by_name in self._by_owner_id.items():
            obj = by_name.get_object(name,obj_id)
            if obj:
                objects.append(
                    obj
                )
        return objects

    def get_objects_for_release(self,release: Release):
        objects: List[T] = []
        for owner_id,by_name in self._by_owner_id.items():
            objects.extend(
                by_name.get_all_for_release(release)
            )
        return objects

    def get_all_for_user(self,user: User):
        if user.git_service_id not in self._by_owner_id:
            return {}
        return self._by_owner_id[user.git_service_id].get_all()

    def get_all_for_user_id(self,user_id: int):
        if user_id not in self._by_owner_id:
            return {}
        return self._by_owner_id[user_id].get_all()
    
    def get_by_name_for_user(self,user: User,name: str):
        if user.git_service_id not in self._by_owner_id:
            return {}
        return self._by_owner_id[user.git_service_id].get_by_name(name)

    def get_object_for_user(self,user: User,name: str,obj_id: str):
        if not user.git_service_id in self._by_owner_id:
            return None
        return self._by_owner_id[user.git_service_id].get_object(name,obj_id)

    def has_object(self,user: User,name: int,obj_id: str):
        by_name = self._by_owner_id.get(user.git_service_id,None)
        if not by_name:
            return False

        return bool(by_name.get_object(name,obj_id))

    def get_latest_for_user_named(self,user: User,name: str):
        scripts = self.get_by_name_for_user(user,name)
        sorted = list(
            scripts.values()
        )
        sorted.sort(key=lambda s:s.release.time,reverse=-1)
        if sorted:
            return sorted[0]
        else:
            return None

    def get_latest_for_name(self,name: str):
        scripts = self.get_by_name(name)
        sorted = list(
            scripts.values()
        )
        sorted.sort(key=lambda s:s.release.time,reverse=-1)
        if sorted:
            return sorted[0]
        else:
            return None

    def is_name_available(self,check_name: str,repo: Repository):
        for name,by_version in self.get_all().items():
            for version,obj in by_version.items():
                if obj.release.repo.git_service_id != repo.git_service_id and name == check_name:
                    return False
        return True


def create_extra_adder(collection: ObjCollection[T]):
    def func(request: Request):
        user: User = request.user
        for extra in user.user_data.allowed_releases:
            split = extra.split(';')
            if len(split) < 3:
                continue
            type,name,release_id = split
            if AppType(type) not in collection.types:
                continue
            if release_id == 'latest':
                latest = collection.get_latest_for_name(name)
                if latest and latest.release.owner_id != user.git_service_id:
                    if not collection.has_object(user,name,latest.version):
                        collection.new_object(
                            latest.clone_to_shared(user.git_service_id)
                        )
            else:
                for key,obj in collection.get_by_name(name).items():
                    if release_id == key and obj.release.owner_id != user.git_service_id:
                        if not collection.has_object(user,name,obj.version):
                            collection.new_object(
                                obj.clone_to_shared(user.git_service_id)
                            )
        for extra_user in user.user_data.allowed_from_user:
            releases = collection.get_all_for_user_id(extra_user)
            for name,objs in releases.items():
                for release_id,obj in objs.items():
                    if not collection.has_object(user,name,release_id):
                        collection.new_object(
                            obj.clone_to_shared(user.git_service_id)
                        )
    return func

def create_extra_remover(collection: ObjCollection[T]):
    def func(request: Request):
        user: User = request.user
        user_repos = collection.get_all_for_user(user)
        listified: List[T] = list(
            filter(
                lambda e: e.release.owner_id != user.git_service_id,
                itertools.chain.from_iterable(
                    map(
                        lambda e: e.values(),
                        user_repos.values()
                    )
            )
        ))
        for obj in listified:
            if len(user.user_data.allowed_releases) == 0 or (len(user.user_data.allowed_releases) == 1 and user.user_data.allowed_releases[0] == ""):
                collection.delete_object(obj)
            else:
                id = f"{obj.name};{obj.release.id}"
                for allowed in user.user_data.allowed_releases:
                    split = allowed.split(';')
                    if len(split) < 3:
                        continue
                    type_, name, version = split
                    if AppType(type_) not in collection.types:
                        continue
                    if not f"{name}:{version}" == id:
                        collection.delete_object(obj)

    return func