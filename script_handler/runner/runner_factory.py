


from abc import ABC,abstractmethod
from .runner_base import Runner
from .port_service import PortService

from .subprocess_runner import PythonShellRunner, PythonVEnvRunner, StreamStrategy, StreamlitVenvRunner

class RunnerFactory(ABC):


    @abstractmethod
    def create_streamlit_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        pass

    @abstractmethod
    def create_python_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        pass

    
    @abstractmethod
    def create_python_shell_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        pass



class VEnvRunnerFactory(RunnerFactory):

    def __init__(
        self,
        venv_activator: str,
        port_service: PortService
    ) -> None:
        self._venv_activator = venv_activator
        self._port_service = port_service


    def create_streamlit_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        return StreamlitVenvRunner(self._venv_activator,self._port_service,work_dir,stream_strategy)

    def create_python_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        return PythonVEnvRunner(self._venv_activator,work_dir,stream_strategy)
    
    def create_python_shell_runner(self,work_dir: str = '/',stream_strategy: StreamStrategy = StreamStrategy.PSEUDO_TERMINAL) -> Runner:
        return PythonShellRunner(self._venv_activator,work_dir,stream_strategy)
    