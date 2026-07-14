import logging
import mimetypes
from pathlib import Path
from .filesystem.local import StorageBackend
from .schemas import FileLike
from ..framework.error import ErrorWithPrompt, NotFound
from .path_conf import get_storage, get_user_storage_root, get_user_meta_root


class UserFSAdapter:
    def __init__(self, email: str, storage: StorageBackend | None = None):
        if storage is None:
            storage = get_storage()
        self.storage = storage

        self._storage_root = get_user_storage_root(email)
        self._meta_root = get_user_meta_root(email)

    @property
    def storage_root(self) -> str:
        return self._storage_root

    @property
    def meta_root(self) -> str:
        return self._meta_root

    async def ls(self, path: str):
        curr_dir = f"{self.storage_root}/{path.lstrip('/')}"
        if not await self.storage.exists(curr_dir):
            return []

        result: dict[str, list[FileLike]] = {}
        for child in await self.storage.listdir(curr_dir):
            full_path = f"{curr_dir.rstrip('/')}/{child}"
            if await self.storage.is_dir(full_path):
                filetype = "dir"
            elif await self.storage.is_file(full_path):
                filetype = "file"
            else:
                continue
            jstree_id = "/" + Path(full_path).relative_to(Path(self.storage_root)).as_posix()  # 取相对路径
            this_item = FileLike(id=jstree_id, type=filetype, text=child)
            result.setdefault(filetype, []).append(this_item)

        # 排序，folder优先在上，其他的子类按名称排序
        return_data = []
        keys = sorted([k for k in result.keys() if k != "dir"])
        if "dir" in result:
            keys.insert(0, "dir")
        for key in keys:
            return_data.extend(sorted(result[key], key=lambda x: x.text))
        return return_data

    async def mkdir(self, path: str):
        dist = f"{self.storage_root}/{path.lstrip('/')}"
        await self.storage.mkdir(dist)

    async def rm(self, path: str):
        delete_path = f"{self.storage_root}/{path.lstrip('/')}"
        if not await self.storage.exists(delete_path):
            return

        if await self.storage.is_dir(delete_path):
            await self.storage.remove_tree(delete_path)
            return

        if await self.storage.is_file(delete_path):
            await self.storage.remove(delete_path)

            # delete meta
            full_meta = f"{self.meta_root}/{path.lstrip('/')}"
            if await self.storage.exists(full_meta):
                await self.storage.remove_tree(full_meta)

    async def rename(self, old_path: str, new_name: str):
        """
        对某个路径进行重新命名

        只能修改最末尾一层，比如 /a/b/c -> /a/b/d，其他情况未定义
        前端目前上传的逻辑符合这个要求。
        """

        # 防止修改根路径，比如 " /", "/ data"
        if old_path.split()[0].strip() == "/":
            raise ErrorWithPrompt("错误的路径")

        origin = f"{self.storage_root}/{old_path.lstrip('/')}"
        if not await self.storage.exists(origin):
            raise ErrorWithPrompt("路径不存在")

        new_path = str(Path(origin).parent / new_name)
        await self.storage.rename(origin, new_path)

        # 重命名meta
        user_meta_root = self.meta_root
        old_meta = f"{user_meta_root}/{old_path.lstrip('/')}"
        if not await self.storage.exists(old_meta):
            return
        new_meta = str(Path(old_meta).parent / new_name)
        logging.debug(f"rename old meta: {old_meta} => {new_meta}")
        await self.storage.rename(old_meta, new_meta)

    async def create_file(self, file: str, content: str | bytes = b''):
        """
        upload 和 new 接口会触发至此, 其他操作皆为更新文件
        1. 不允许覆盖已有文件
        2. 清除 meta 目录（fallback保护，正常情况 meta 不会存在）

        """
        dist_file = f"{self.storage_root}/{file.lstrip('/')}"
        if await self.storage.exists(dist_file) and await self.storage.is_file(path=dist_file):
            raise ErrorWithPrompt("文件已存在")

        dist_meta = f"{self.meta_root}/{file.lstrip('/')}"
        if await self.storage.exists(dist_meta):
            await self.storage.remove_tree(dist_meta)

        if isinstance(content, str):
            bin_content = content.encode("utf-8", errors="replace")
        else:
            bin_content = content
        await self.storage.write_bytes(dist_file, bin_content)

    async def get_original_image_file(self, filepath: str) -> tuple[str, bytes | None]:
        """
        获取原始图片文件内容

        直接读取 storage 目录下的图片文件，不走版本还原逻辑。
        用于下载、预览等不需要版本信息的场景。

        Params:
            filepath : 文件相对路径

        Returns:
            (mimetype, content) : MIME 类型和文件二进制内容

        Raises:
            NotFound: 文件不存在时抛出
        """
        target_file = f"{self.storage_root}/{filepath.lstrip('/')}"
        if not await self.storage.exists(target_file):
            raise NotFound()

        mimetype = mimetypes.guess_type(str(target_file))[0] or "application/octet-stream"
        if isinstance(mimetype, str) and mimetype.startswith("image/"):
            content = await self.storage.read_bytes(target_file)
            return mimetype, content
        return "", None

    async def move(self, src: str, dst: str):
        """

        Params:
            src: str, 被移动的文件或目录，eg: /1629423707000.jpg, /blog/sub
            dst: str, 一定是个目录 /blog
        """

        src_full = f"{self.storage_root}/{src.lstrip('/')}"
        dst_full = f"{self.storage_root}/{dst.lstrip('/')}"

        if not await self.storage.exists(dst_full):
            raise ErrorWithPrompt("目标位置不存在")
        if not await self.storage.is_dir(dst_full):
            raise ErrorWithPrompt("目标位置必须是目录")
        if not await self.storage.exists(src_full):
            raise ErrorWithPrompt("要移动的文件或目录不存在")

        if f"{dst_full}/".startswith(f"{src_full}/"):
            raise ErrorWithPrompt("无法移动到自身的子文件夹内")

        src_name = src_full.split('/')[-1]
        target_path = f"{dst_full.rstrip('/')}/{src_name}"
        if await self.storage.exists(target_path):
            # 区分文件和目录，给更友好的错误提示
            if await self.storage.is_dir(target_path):
                raise ErrorWithPrompt(f"目标位置已存在同名目录：{src_name}")
            else:
                raise ErrorWithPrompt(f"目标位置已存在同名文件：{src_name}")

        # 检查 meta
        user_meta_root = self.meta_root
        old_meta = f"{user_meta_root}/{src.lstrip('/')}"
        target_meta_parent = f"{user_meta_root}/{dst.lstrip('/')}"
        target_meta_path = f"{target_meta_parent}/{src_name}"

        try:
            await self.storage.rename(src_full, target_path)
            # 针对 meta 强制覆盖。即使是图片文件，仍然可能有meta, 因为包含 share 等配置文件
            if await self.storage.exists(old_meta):
                # 清空已存在的 meta 目录树
                if await self.storage.exists(target_meta_path):
                    await self.storage.remove_tree(target_meta_path)
                await self.storage.mkdir(target_meta_parent)
                await self.storage.rename(old_meta, target_meta_path)
        except Exception as e:
            # 兜底捕获底层异常，避免暴露内部实现
            raise ErrorWithPrompt(f"移动失败：{str(e)}")
