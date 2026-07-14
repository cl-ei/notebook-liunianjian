import mimetypes
from src.framework.error import ErrorWithPrompt, NotFound
from .filesystem.local import StorageBackend
from .path_conf import get_storage, get_user_storage_root, get_user_meta_root, get_share_mark_filepath
from .versioning_adaptor import VersioningAdapter


class ShareAdapter:
    """
    文件分享管理

    分享的判断逻辑：在文件的 meta 目录下创建一个名为 share 的空标记文件，
    share 文件存在即视为已分享，不存在即未分享。
    这是一种基于文件系统的最小化实现，无需维护额外的分享状态表。

    读取分享内容时，根据文件类型做区分：
    - 图片文件：直接返回二进制内容，浏览器可直接渲染
    - 其他文件：通过版本系统还原最新版本全文后返回

    使用方式：
        adapter = ShareAdapter(email)
        await adapter.create_share("path/to/file")   # 创建分享
        await adapter.get_share("path/to/file")      # 获取分享内容
    """
    def __init__(self, email: str, storage: StorageBackend | None = None):
        if storage is None:
            storage = get_storage()
        self.storage = storage
        self._email = email

    @property
    def email(self) -> str:
        return self._email

    @property
    def storage_root(self) -> str:
        return get_user_storage_root(self.email)

    @property
    def meta_root(self) -> str:
        return get_user_meta_root(self.email)

    async def enable_share(self, file: str):
        """创建文件分享"""
        target_file = f"{self.storage_root}/{file.lstrip('/')}"
        if not await self.storage.exists(target_file) or not await self.storage.is_file(target_file):
            raise ErrorWithPrompt("文件不存在")

        share_file = get_share_mark_filepath(self.email, file)
        await self.storage.write_text(share_file, "")
        return True

    async def disable_share(self, file: str):
        """ 取消分享 """
        mark_file = get_share_mark_filepath(self.email, file)
        if await self.storage.exists(mark_file) and await self.storage.is_file(mark_file):
            await self.storage.remove(mark_file)
        return True

    async def test_share(self, file: str) -> bool:
        share_file = get_share_mark_filepath(self.email, file)
        return await self.storage.exists(share_file)

    async def get_share(self, file: str) -> tuple[str, str | bytes]:
        """ 获取分享的 mimetype 和文件内容 """
        if not await self.test_share(file):
            raise NotFound()

        # 针对图片文件，直接读取
        target_file = f"{self.storage_root}/{file.lstrip('/')}"
        mimetype = mimetypes.guess_type(target_file)[0] or "application/octet-stream"
        if isinstance(mimetype, str) and mimetype.startswith("image/"):
            bin_content = await self.storage.read_bytes(target_file)
            return mimetype, bin_content

        content = await VersioningAdapter(self.email).get_latest_file_content(file)
        return mimetype or "", content
