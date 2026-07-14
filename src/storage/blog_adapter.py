import logging
import traceback

from .filesystem.base import StorageBackend
from .path_conf import get_storage, get_user_blog_version_filepath


class BlogAdapter:
    def __init__(self, email: str, storage: StorageBackend | None = None):
        if storage is None:
            storage = get_storage()
            self.storage = storage

        self._email = email

    @property
    def email(self) -> str:
        return self._email

    async def set_version(self, version: str) -> bool:
        blog_ver_file = get_user_blog_version_filepath(self.email)
        try:
            await self.storage.write_text(blog_ver_file, version)
            return True

        except Exception as e:
            logging.error(f"error happened in write blog version: {e}, version: {version}\n{traceback.format_exc()}")
            return False

    async def get_version(self) -> str:
        blog_ver_file = get_user_blog_version_filepath(self.email)
        try:
            return await self.storage.read_text(blog_ver_file)
        except FileNotFoundError:
            return ""
