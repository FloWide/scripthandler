from abc import abstractmethod
import asyncio
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
import os
import pty
import termios
from typing import Dict,List, Optional, Union,Tuple

from .port_service import PortService

from .runner_base import Runner,RunnerStream

import logging


class SubProcessStream(RunnerStream):

    def __init__(self,proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    async def readline(self) -> bytes:
        if not self._proc.stdout:
            raise ValueError("Process has no stdout")            
        
        return await self._proc.stdout.readline()

    async def read(self, n: int = 1024) -> bytes:
        if not self._proc.stdout:
            raise ValueError("Process has no stdout")            

        return await self._proc.stdout.read(n)

    async def writeline(self, data: bytes, *args, **kwargs) -> None:
        if not self._proc.stdin:
            raise ValueError("Process has no stdin")


        self._proc.stdin.writelines([data,'\n\r'.encode()])
        
        await self._proc.stdin.drain()

    async def write(self, data: bytes, *args, **kwargs) -> None:
        if not self._proc.stdin:
            raise ValueError("Process has no stdin")

        self._proc.stdin.write(data)
        await self._proc.stdin.drain()
    
    def write_eof(self) -> None:
        if not self._proc.stdin:
            raise ValueError("Process has no stdin")
        self._proc.stdin.write_eof()

class FileDescriptorStream(RunnerStream):

    def __init__(self,fd: int,proc: asyncio.subprocess.Process) -> None:
        self._fd = fd
        self._executor = ThreadPoolExecutor(4)
        self._proc = proc

    async def readline(self) -> bytes:
        return await self.read()

    async def read(self, n: int = 1024) -> bytes:
        try:
            data = await asyncio.get_running_loop().run_in_executor(self._executor,lambda: os.read(self._fd,n))
            logging.debug(f"Reading data from subproccess: {data}")
            return data
        except (OSError,RuntimeError) as e:
            logging.debug(e)

    async def write(self, data: bytes, *args, **kwargs) -> None:
        logging.debug(f"Writing data to subprocess {data}")
        try:
            await asyncio.get_running_loop().run_in_executor(self._executor,lambda: os.write(self._fd,data))
        except (OSError,RuntimeError) as e:
            logging.debug(e)

    async def writeline(self, data: bytes, *args, **kwargs) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(self._executor,lambda: os.write(self._fd,str(f'{data.decode()}\n').encode()))
        except (OSError,RuntimeError) as e:
            logging.debug(e)

    def write_eof(self) -> None:
        pass


class StreamStrategy(Enum):
    PSEUDO_TERMINAL = 0
    SUBPROCESS_PIPE = 1
    DEVNULL = 3

class SubProcessRunner(Runner):
    
    _proc: asyncio.subprocess.Process


    def __init__(
        self,
        work_dir: str,
        stream_strategy: StreamStrategy = StreamStrategy.DEVNULL
    ) -> None:
        super().__init__()
        self._work_dir = work_dir
        self._stream_strategy = stream_strategy
        self._proc = None
        self._run_start_event = asyncio.Event()
        self._master_fd = None
        self._slave_fd = None

    async def run(self, entry_file: str, env_variables: Optional[Dict[str, str]] = None, cli_args: Optional[List[str]] = None) -> bool:
        
        if self.is_running:
            try:
                await self.terminate(10)
            except asyncio.TimeoutError:
                await self.kill()

        if self._stream_strategy == StreamStrategy.DEVNULL:
            stream_pipes = (asyncio.subprocess.DEVNULL,asyncio.subprocess.DEVNULL,asyncio.subprocess.DEVNULL)
        elif self._stream_strategy == StreamStrategy.SUBPROCESS_PIPE:
            stream_pipes = (asyncio.subprocess.PIPE,asyncio.subprocess.PIPE,asyncio.subprocess.STDOUT)
        elif self._stream_strategy == StreamStrategy.PSEUDO_TERMINAL:
            self._master_fd,self._slave_fd = pty.openpty()
            self._configure_pty()
            stream_pipes = (self._slave_fd,self._slave_fd,self._slave_fd)
        else:
            raise RuntimeError(f"Invalid stream strategy: {self._stream_strategy}")
        if (await self._run_impl(entry_file,stream_pipes,env_variables,cli_args)):
            if self._stream_strategy == StreamStrategy.PSEUDO_TERMINAL:
                self._streams = FileDescriptorStream(self._master_fd,self._proc)
            elif self._stream_strategy == StreamStrategy.SUBPROCESS_PIPE:
                self._streams = SubProcessStream(self._proc)
            else:
                self._streams = None
            self._run_start_event.set()
            return True
        else:
            return False

    @abstractmethod
    async def _run_impl(self,entry_file: str,stream_pipes: Tuple[int,int,int], env_variables: Optional[Dict[str, str]], cli_args: Optional[List[str]]):
        pass
    
    @property
    def is_running(self) -> bool:
        return self._proc and self._proc.returncode == None

    @property
    def work_dir(self) -> str:
        return self._work_dir

    @property
    def run_start_event(self) -> asyncio.Event:
        return self._run_start_event

    async def wait(self) -> int:
        ret_code = await self._proc.wait()
        if self._master_fd:
            os.close(self._master_fd)
            self._master_fd = None
        if self._slave_fd:
            os.close(self._slave_fd)
            self._slave_fd = None
        self._run_start_event.clear()
        return ret_code

    async def _terminate_impl(self):
        self._proc.terminate()

    async def _kill_impl(self):
        self._proc.kill()

    @property
    def streams(self) -> RunnerStream:
        return self._streams

    @staticmethod
    async def create_subprocess(cmd: str | bytes,stream_pipes: Tuple[int,int,int],**kwargs):
        return await asyncio.create_subprocess_shell(
            cmd,
            stdin=stream_pipes[0],
            stdout=stream_pipes[1],
            stderr=stream_pipes[2],
            **kwargs
        )


    def _configure_pty(self):
        attr = termios.tcgetattr(self._slave_fd)
        attr[3] = attr[3] & ~termios.ISIG
        termios.tcsetattr(self._slave_fd,termios.TCSANOW,attr)
        attr = termios.tcgetattr(self._master_fd)
        attr[3] = attr[3] & ~termios.ISIG
        termios.tcsetattr(self._master_fd,termios.TCSANOW,attr)

class PythonShellRunner(SubProcessRunner):

    def __init__(
        self,
        venv_activator: str,
        work_dir: str,
        stream_strategy: StreamStrategy = StreamStrategy.DEVNULL
    ) -> None:
        super().__init__(work_dir,stream_strategy)
        self._venv_activator = venv_activator

    async def _run_impl(self, entry_file: str,stream_pipes: Tuple[int,int,int],env_variables: Optional[Dict[str, str]], cli_args: Optional[List[str]]):
        self._proc = await SubProcessRunner.create_subprocess(
            f". {self._venv_activator}; cd {self.work_dir};exec python",
            stream_pipes
        )
        return True


    def clone(self):
        return PythonShellRunner(
            self._venv_activator,
            self._work_dir,
            self._stream_strategy
        )
        

class PythonVEnvRunner(SubProcessRunner):

    def __init__(
        self,
        venv_activator: str,
        work_dir: str,
        stream_strategy: StreamStrategy = StreamStrategy.DEVNULL
    ) -> None:
        super().__init__(work_dir,stream_strategy)
        self._venv_activator = venv_activator

    async def _run_impl(self, entry_file: str,stream_pipes: Tuple[int,int,int], env_variables: Optional[Dict[str, str]], cli_args: Optional[List[str]]):
        env = ''
        if env_variables:
            for key,value in env_variables.items():
                env += f'{key}={value} '

        self._proc = await SubProcessRunner.create_subprocess(
            f". {self._venv_activator}; cd {self.work_dir}; exec env {env} python -u {entry_file} {' '.join(cli_args) if cli_args else ''} ",
            stream_pipes
        )
        return True

    def clone(self):
        return PythonVEnvRunner(
            self._venv_activator,
            self._work_dir,
            self._stream_strategy
        )

class StreamlitVenvRunner(SubProcessRunner):

    _port: Union[int,None]

    def __init__(
        self,
        venv_activator: str,
        port_service: PortService,
        work_dir: str,
        stream_strategy: StreamStrategy = StreamStrategy.DEVNULL
    ) -> None:
        super().__init__(work_dir,stream_strategy)
        self._venv_activator = venv_activator
        self._port_service = port_service

    async def _run_impl(self, entry_file: str, stream_pipes: Tuple[int,int,int],env_variables: Optional[Dict[str, str]], cli_args: Optional[List[str]]):
        env = ''
        if env_variables:
            for key,value in env_variables.items():
                env += f'{key}={value} '

        self._port = self._port_service.acquire_port()

        self._proc = await SubProcessRunner.create_subprocess(
            f". {self._venv_activator}; cd {self.work_dir}; exec env {env} streamlit run {entry_file} --server.port {self._port}  --server.headless true -- {' '.join(cli_args) if cli_args else ''}",
            stream_pipes
        )
        await asyncio.sleep(3)
        return self._proc.returncode == None

    async def wait(self) -> int:
        ret = await super().wait()
        self._release_port()
        return ret

    def _release_port(self):
        if self._port:
            self._port_service.release_port(self._port)
            self._port = None

    def clone(self):
        return StreamlitVenvRunner(
            self._venv_activator,
            self._port_service,
            self._work_dir,
            self._stream_strategy
        )

    @property
    def port(self) -> Optional[int]:
        return self._port
        
        
