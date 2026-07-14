from abc import ABC, abstractmethod
from typing import List, Tuple


class StorageBackend(ABC):

    @abstractmethod
    async def read_text(self, path: str, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    async def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None: ...

    @abstractmethod
    async def write_bytes(self, path: str, content: bytes) -> None: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def is_file(self, path: str) -> bool: ...

    @abstractmethod
    async def is_dir(self, path: str) -> bool: ...

    @abstractmethod
    async def mkdir(self, path: str, parents: bool = True) -> None: ...

    @abstractmethod
    async def remove(self, path: str) -> None: ...

    @abstractmethod
    async def remove_tree(self, path: str) -> None: ...

    @abstractmethod
    async def rename(self, src: str, dst: str) -> None: ...

    @abstractmethod
    async def listdir(self, path: str) -> List[str]: ...

    @abstractmethod
    async def stat(self, path: str) -> Tuple[int, float]:
        """
        return (size, mtime)
        """

    @abstractmethod
    async def copy(self, src: str, dst) -> None:
        """
        copy file
        """
