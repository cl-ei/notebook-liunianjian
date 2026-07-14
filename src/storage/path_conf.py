from src.framework.config import STORAGE_ROOT
from .filesystem.local import StorageBackend, LocalStorage

_storage: StorageBackend | None = None


def get_storage(create: bool = False) -> StorageBackend:
    # 添加动态逻辑
    if create:
        return LocalStorage()

    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage


def gen_tokens_filepath(email: str) -> str:
    return f"{STORAGE_ROOT}/{email}/auth/tokens.txt"


def gen_passwd_filepath(email: str):
    return f"{STORAGE_ROOT}/{email}/auth/pass.txt"


def get_user_storage_root(email: str) -> str:
    return f"{STORAGE_ROOT}/{email}/storage"


def get_user_meta_root(email: str) -> str:
    return f"{STORAGE_ROOT}/{email}/meta"


def get_share_mark_filepath(email: str, file: str) -> str:
    meta = get_user_meta_root(email)
    return f"{meta}/{file.lstrip('/')}/share"
