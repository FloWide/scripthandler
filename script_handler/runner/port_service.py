
from typing import Iterable

from sortedcontainers import SortedSet


class PortService:

    def __init__(self,ports: Iterable[int]) -> None:
        self._ports = SortedSet(ports)

    def acquire_port(self) -> int:
        return self._ports.pop(0)

    def release_port(self,port: int):
        self._ports.add(port)
