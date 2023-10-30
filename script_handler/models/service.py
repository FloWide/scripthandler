


import asyncio
from enum import Enum
import io
import os
from platform import release
import time
from typing import ClassVar, Optional, Tuple
from xmlrpc.client import boolean

import aiofiles

from script_handler.models.releases import Release

from ..runner.runner_base import Runner

from .repository import Repository

from .app_config import AppConfig
from .base_model import BaseModel
from .script import State
from datetime import datetime
import json

import logging

class State(str,Enum):
    ACTIVE = 'active'
    STARTING = 'starting'
    INACTIVE = 'inactive'
    FAILED_TO_START = 'failed to start'

class ServiceModel(BaseModel):
    state: State = State.INACTIVE
    exit_code: Optional[int] = None
    config: AppConfig = None
    name: str = ''
    started_at: int = None
    version: str = None
    created_at: int = None
    compound_id: Tuple[str,str] = None
    repository_id: int = None
    owner_name: str = None
    enabled: bool = False


class Service(ServiceModel):

    _startup_tries: ClassVar[int] = 5

    _logs_root: ClassVar[str] = '/var/log/streamlit-api'

    _release: Release
    
    _runner: Runner

    _log_file: str
    _enabled_file: str

    def __init__(
        self,
        release: Release,
        name: str,
        config: AppConfig,
        runner: Runner,
    ):
        super().__init__(
            version=release.id,
            config=config,
            name=name,
            created_at=release.time,
            compound_id=(name,release.id),
            owner_name=release.repo.owner_name,
            repository_id=release.repo.git_service_id
        )
        
        self._release = release
        self._runner = runner
        self._runner.set_working_dir(release.root_path)
        self._log_file = os.path.join(self._release.root_path,f'{name}.logs')
        self._enabled_file = os.path.join(self._release.root_path,f'{name}.enabled')

        if os.path.exists(self._enabled_file):
            with open(self._enabled_file,'r') as f:
                try:
                    self.enabled = json.loads(f.read())
                except json.JSONDecodeError:
                    self.enabled = False
        if self.enabled:
            logging.info(f"Autostarting user service: {self}")
            asyncio.ensure_future(self.run())

    async def run(self):

        if not self._release.loaded_on_disk:
            self._release.load()
        self._ensure_log_file_exists(self._log_file)

        if self._runner.is_running:
            return

        self.state = State.STARTING
        await self._write_to_log(f"Starting service...")
        ready = False
        tries = 0
        while not ready and tries < Service._startup_tries:
            ready = await self._runner.run(self.config.config.entry_file,{**self.config.config.env,**{"RELEASE_MODE":True}},self.config.config.cli_args)
            tries += 1
        if not ready:
            self.state = State.FAILED_TO_START
            self.exit_code = await self._runner.wait() # returns immedieatly
            await self._write_to_log(f"Failed to start process. exit-code: {self.exit_code}")
        else:
            self.state = State.ACTIVE
            self.started_at = int(time.time())
            asyncio.ensure_future(self._wait_task())
            asyncio.ensure_future(self._log_task())

    async def terminate(self,timeout: int = 10) -> bool:
        try:
            await self._runner.terminate(timeout)
            await self._write_to_log("Service has been terminated")
            return True
        except TimeoutError as e:
            return False

    async def kill(self):
        await self._runner.kill()
        await self._write_to_log("Service has been killed")

    async def restart(self):
        if not self._runner.is_running:
            await self.run()
            return
        await self._write_to_log("Restarting service...")
        terminate_result = await self.terminate()
        if not terminate_result:
            await self.kill()
        await self.run()

    async def set_enabled(self,enabled:bool,auto_start: bool = False):
        self.enabled = enabled
        
        with open(self._enabled_file,'w') as f:
            f.write(json.dumps(self.enabled))

        if self.enabled and auto_start:
            if not self._runner.is_running:
                await self.run()
        elif not self.enabled and self._runner.is_running:
            terminate_result = await self.terminate()
            if not terminate_result:
                await self.kill()

    async def _wait_task(self):
        self.exit_code = await self._runner.wait()
        self.state = State.INACTIVE
        self.started_at = None
        await self._write_to_log(f"Process exited with code: {self.exit_code}")
        if self.enabled:
            await self.run()

    async def _log_task(self):
        async with aiofiles.open(self._log_file,'a') as f:
           async for line in self._runner.streams.stream_lines():
               await f.write(f"[{datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}] [{self.name}] {line.decode()}")
               await f.flush()

    async def _write_to_log(self,data: str):
        if not os.path.exists(self._log_file):
            return
        async with aiofiles.open(self._log_file,'a') as f:
            await f.write(f"[{datetime.utcnow().strftime('%Y/%m/%d, %H:%M:%S')}] [ServiceHandler] {data} \n")
            await f.flush()

    
    async def get_logs(self,limit: int = 200) -> str:
        if not os.path.exists(self._log_file):
            return ''

        logs = ''
        async with aiofiles.open(self._log_file,'r') as f:
            counter = 0
            async for line in _reverse_read_lines(f):
                if counter >= limit:
                    break
                logs += line
                counter += 1
        reversed = logs.splitlines()
        reversed.reverse()
        return '\n'.join(reversed)

    def _ensure_log_file_exists(self,file: str):
        if os.path.exists(file):
            return
        os.makedirs(os.path.dirname(file),exist_ok=True)
        open(file,'a').close()
        
    def clone_to_shared(self,shared_owner_id):
        cloned_release = self._release.clone_to_shared(shared_owner_id)
        cloned_runner = self._runner.clone()
        cloned_runner.set_working_dir(cloned_release.root_path)
        return Service(
            cloned_release,
            self.name,
            self.config.copy(),
            cloned_runner
        )

    @property
    def repo(self):
        return self._release.repo

    @property
    def runner(self):
        return self._runner

    @property
    def release(self):
        return self._release


    @classmethod
    def set_logs_root(cls,logs_root: str):
        cls._logs_root = logs_root





async def _reverse_read_lines(fp, buf_size=8192):  # pylint: disable=invalid-name
        """
        Async generator that returns the lines of a file in reverse order.
        ref: https://stackoverflow.com/a/23646049/8776239
        and: https://stackoverflow.com/questions/2301789/read-a-file-in-reverse-order-using-python
        """
        segment = None  # holds possible incomplete segment at the beginning of the buffer
        offset = 0
        await fp.seek(0, io.SEEK_END)
        file_size = remaining_size = await fp.tell()
        while remaining_size > 0:
            offset = min(file_size, offset + buf_size)
            await fp.seek(file_size - offset)
            buffer = await fp.read(min(remaining_size, buf_size))
            remaining_size -= buf_size
            lines = buffer.splitlines(True)
            # the first line of the buffer is probably not a complete line so
            # we'll save it and append it to the last line of the next buffer
            # we read
            if segment is not None:
                # if the previous chunk starts right from the beginning of line
                # do not concat the segment to the last line of new chunk
                # instead, yield the segment first
                if buffer[-1] == '\n':
                    # print 'buffer ends with newline'
                    yield segment
                else:
                    lines[-1] += segment
                    # print 'enlarged last line to >{}<, len {}'.format(lines[-1], len(lines))
            segment = lines[0]
            for index in range(len(lines) - 1, 0, -1):
                l = lines[index]
                if l:
                    yield l
        # Don't yield None if the file was empty
        if segment is not None:
            yield segment