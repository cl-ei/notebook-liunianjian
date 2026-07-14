import shutil
import aiofiles
import aiofiles.os as aios
from pathlib import Path

from .base import StorageBackend
from src.framework.config import STORAGE_ROOT


class LocalStorage(StorageBackend):
    def __init__(self, root: Path = STORAGE_ROOT):
        self.root = Path(root)

    def _resolve(self, path: str) -> Path:
        real_path = (self.root / path).resolve()
        # 防止 ../.. 逃逸
        if not real_path.is_relative_to(self.root):
            raise PermissionError("Invalid path")
        return real_path

    async def read_text(self, path: str, encoding="utf-8") -> str:
        async with aiofiles.open(self._resolve(path), "r", encoding=encoding) as f:
            return await f.read()

    async def read_bytes(self, path: str) -> bytes:
        async with aiofiles.open(self._resolve(path), "rb") as f:
            return await f.read()

    async def write_text(self, path: str, content: str, encoding="utf-8") -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(p, "w", encoding=encoding) as f:
            await f.write(content)

    async def write_bytes(self, path: str, content: bytes) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(p, "wb") as f:
            await f.write(content)

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def is_file(self, path: str) -> bool:
        return self._resolve(path).is_file()

    async def is_dir(self, path: str) -> bool:
        return self._resolve(path).is_dir()

    async def mkdir(self, path: str, parents=True) -> None:
        self._resolve(path).mkdir(parents=parents, exist_ok=True)

    async def remove(self, path: str) -> None:
        await aios.remove(self._resolve(path))

    async def remove_tree(self, path: str) -> None:
        shutil.rmtree(str(self._resolve(path)))

    async def rename(self, src: str, dst: str) -> None:
        await aios.rename(self._resolve(src), self._resolve(dst))

    async def listdir(self, path: str) -> list[str]:
        return await aios.listdir(self._resolve(path))  # noqa

    async def stat(self, path: str) -> tuple[int, float]:
        st = await aios.stat(self._resolve(path))
        return st.st_size, st.st_mtime
