
from abc import ABC,abstractmethod
import asyncio
from typing import Tuple, Union,AsyncGenerator,Optional,Dict,List
import asyncio




class RunnerStream(ABC):
    
    @abstractmethod
    async def readline(self) -> bytes:
        pass
    
    @abstractmethod
    async def read(self,n: int = 1024) -> bytes:
        pass

    async def stream_read(self,n: int = 1024) -> AsyncGenerator[bytes,None]:
        while True:
            data = await self.read(n)
            if not data:
                break
            yield data
    
    async def stream_lines(self) -> AsyncGenerator[bytes,None]:
        while True:
            data = await self.readline()
            if not data:
                break
            yield data
    
    @abstractmethod
    async def writeline(self,data: bytes,*args,**kwargs) -> None:
        pass
    
    @abstractmethod
    async def write(self,data: bytes,*args,**kwargs) -> None:
        pass
    
    @abstractmethod
    def write_eof(self) -> None:
        pass
    

class Runner(ABC):

    _work_dir: str

    @abstractmethod
    async def run(self,entry_file: str,env_variables: Optional[Dict[str,str]] = None,cli_args: Optional[List[str]] = None) -> bool:
        pass

    async def terminate(self,timeout: Union[float,None] = None) -> int:
        if timeout:
            await self._terminate_impl()
            return await self.wait_for(timeout)
        else:
            await self._terminate_impl()
            return await self.wait()
    
    async def kill(self,timeout: Union[float,None] = None) -> int:
        if timeout:
            await self._kill_impl()
            return await self.wait_for(timeout)
        else:
            await self._kill_impl()
            return await self.wait()
    
    async def wait_for(self,timeout: float) -> int:
        return await asyncio.wait_for(self.wait(),timeout)

    @property
    def port(self) -> Optional[int]:
        return None    

    @property
    @abstractmethod
    def run_start_event(self) -> asyncio.Event:
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        pass
    
    @property
    @abstractmethod
    def work_dir(self) -> str:
        pass

    @property
    @abstractmethod
    def streams(self) -> RunnerStream:
        pass

    @abstractmethod
    async def wait(self) -> int:
        pass
    
    @abstractmethod
    async def _terminate_impl(self):
        pass

    @abstractmethod
    async def _kill_impl(self):
        pass
    
    @abstractmethod
    def clone(self) -> "Runner":
        pass

    def set_working_dir(self,dir: str):
        if self.is_running:
            raise RunnerError('Cannot change working directory while running')

        self._work_dir = dir


class RunnerError(RuntimeError):
    pass