

import asyncio
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from script_handler.models.releases import Release

from .base_model import BaseModel
from .app_config import AppConfig
from ..runner.runner_base import Runner
from .repository import Repository
from enum import Enum

class State(str,Enum):
    ACTIVE = "active"
    STARTING = "starting"
    INACTIVE = "inactive"


class ScriptModel(BaseModel):
    state: State = State.INACTIVE
    port: Optional[int] = None
    exit_code: Optional[int] = None
    name: str = ''
    config: AppConfig = None
    version: str = None
    type: Literal['python'] | Literal['streamlit']
    created_at: int = None
    compound_id: Tuple[str,str] = None
    repository_id: int = None
    owner_name: str = None

class Script(ScriptModel):

    state: State = State.INACTIVE
    port: Optional[int] = None
    exit_code: Optional[int] = None
    config: AppConfig
    
    _release: Release

    _runner: Runner

    def __init__(
        self,
        release: Release,
        name: str,
        config: AppConfig,
        runner: Runner,
    ) -> None:
        self._release = release
        self._runner = runner
        self._runner.set_working_dir(release.root_path)
        super().__init__(
            version=self._release.id,
            name=name,
            config=config,
            type=config.type,
            created_at=self._release.time,
            compound_id=(name,release.id),
            owner_name=release.repo.owner_name,
            repository_id=release.repo.git_service_id
        )


    async def run(
        self,
        entry_file: Optional[str] = None,
        env: Optional[Dict[str,str]] = None,
        cli_args: Optional[List[Any]] = None,
    ):
        if not self._release.loaded_on_disk:
            self._release.load()

        self.state = State.STARTING
        ready = await self._runner.run(
            entry_file or self.config.config.entry_file,
            {**self.config.config.env,**env,**{"RELEASE_MODE":True}} if env else {**self.config.config.env,**{"RELEASE_MODE":True}},
            cli_args or self.config.config.cli_args
        )
        self.state = State.ACTIVE if ready else State.INACTIVE
        self.port = self._runner.port
        asyncio.ensure_future(self._wait_task())

    async def terminate(self,timeout: int = 10) -> bool:
        try:
            await self._runner.terminate(timeout)
            return True
        except TimeoutError as e:
            return False

    async def kill(self):
        await self._runner.kill()

    async def _wait_task(self):
        self.exit_code = await self._runner.wait()
        self.port = None
        self.state = State.INACTIVE

    def clone_to_shared(self,shared_owner_id):
        cloned_release = self._release.clone_to_shared(shared_owner_id)
        cloned_runner = self._runner.clone()
        cloned_runner.set_working_dir(cloned_release.root_path)
        return Script(
            cloned_release,
            self.name,
            self.config.copy(),
            cloned_runner
        )

    @property
    def repo(self) -> Repository:
        return self._release.repo

    @property
    def runner(self):
        return self._runner

    @property
    def release(self):
        return self._release
