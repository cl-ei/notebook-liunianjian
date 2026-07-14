from .filesystem.local import StorageBackend
from .path_conf import get_storage, gen_passwd_filepath, gen_tokens_filepath


class AuthAdapter:
    def __init__(self, email: str, storage: StorageBackend | None = None):
        if storage is None:
            storage = get_storage()
        self.storage = storage

        self._passwd_filepath = gen_passwd_filepath(email)
        self._tokens_filepath = gen_tokens_filepath(email)

    @property
    def tokens_filepath(self) -> str:
        return self._tokens_filepath

    @property
    def passwd_filepath(self) -> str:
        return self._passwd_filepath

    async def load_user_token(self) -> list[str]:
        try:
            content = await self.storage.read_text(self.tokens_filepath)
        except: # noqa
            return []

        return content.split("\n")

    async def get_encrypted_password(self) -> str:
        try:
            return await self.storage.read_text(self.passwd_filepath)
        except FileNotFoundError:
            return ""

    async def set_encrypted_password(self, token: str) -> None:
        await self.storage.write_text(self.passwd_filepath, token)

    async def add_user_token(self, token: str) -> None:
        """
        将 token 追加到用户文件中，如果文件超过 100KB，则清理最久远的

        """
        try:
            old = await self.storage.read_text(self.tokens_filepath)
            token_list = [a for a in old.split("\n") if a.strip()]
        except FileNotFoundError:
            token_list = []

        new_content = "\n".join(token_list[-9:] + [token])
        await self.storage.write_text(self.tokens_filepath, new_content)

    async def delete_user_token(self, token: str) -> None:
        if not await self.storage.exists(self.tokens_filepath):
            return

        content = await self.storage.read_text(self.tokens_filepath)

        token_list = content.split("\n")
        new_content = "\n".join([t for t in token_list if t != token])

        await self.storage.write_text(self.tokens_filepath, new_content)

    async def delete_all_user_token(self) -> None:
        await self.storage.write_text(self.tokens_filepath, "")
