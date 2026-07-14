import hashlib
from fastapi import Cookie, Request
from src import utils
from src.utils.global_lock import GlobalLock
from src.framework.error import ErrorWithPrompt
from src.storage.auth_adapter import AuthAdapter
from src.framework.config import IS_PROD, RESERVED_EMAIL


class Encryptor:
    @staticmethod
    def encode(text: str) -> str:
        hash_object = hashlib.sha256(text.encode())
        return hash_object.hexdigest()


class AuthMgr:

    @classmethod
    def _gen_temporary_token(cls) -> str:
        token_key = utils.randstr(24)
        return token_key

    @classmethod
    async def register(cls, email: str, password: str) -> str:
        if IS_PROD:
            raise ErrorWithPrompt("本站点已关闭注册")

        if email == RESERVED_EMAIL:
            raise ErrorWithPrompt("禁止使用保留的email")

        async with GlobalLock(name=f"login:{email}", try_times=1) as lock:
            if not lock.locked:
                raise ErrorWithPrompt("操作频繁，请稍后再试")

            adapter = AuthAdapter(email)
            encrypted_password = await adapter.get_encrypted_password()
            if encrypted_password:
                raise ErrorWithPrompt("用户已存在，请登录。如果遗忘密码，请联系站长")

            encrypted_key = Encryptor.encode(password)
            await adapter.set_encrypted_password(encrypted_key)

            token = cls._gen_temporary_token()
            await adapter.add_user_token(token)
            return token

    @classmethod
    async def login(cls, email: str, password: str) -> str:
        async with GlobalLock(name=f"login:{email}", try_times=1) as lock:
            if not lock.locked:
                raise ErrorWithPrompt("登录频繁，请稍后再试")
            adapter = AuthAdapter(email)
            existed_encrypted = await adapter.get_encrypted_password()
            check_pass = Encryptor.encode(password)
            if check_pass != existed_encrypted:
                raise ErrorWithPrompt("email或密码错误")

            token = cls._gen_temporary_token()
            await adapter.add_user_token(token)
            return token

    @classmethod
    async def logout(cls, email: str, token: str) -> None:
        await AuthAdapter(email).delete_user_token(token)

    @classmethod
    async def change_password(cls, email, old_password, new_password) -> None:
        async with GlobalLock(name=f"login:{email}", try_times=1) as lock:
            if not lock.locked:
                raise ErrorWithPrompt("操作频繁，请稍后再试")
            adapter = AuthAdapter(email)
            encrypted_password = await adapter.get_encrypted_password()
            encrypted_old = Encryptor.encode(old_password)
            if encrypted_old != encrypted_password:
                raise ErrorWithPrompt("email或密码错误")

            # 写入新密码
            encrypted_key = Encryptor.encode(new_password)
            await adapter.set_encrypted_password(encrypted_key)

            # 删除 token
            await adapter.delete_all_user_token()

    @classmethod
    async def force_reset_password(cls, email: str, password: str):
        encrypted_key = Encryptor.encode(password)
        adapter = AuthAdapter(email)
        await adapter.set_encrypted_password(encrypted_key)
        await adapter.delete_all_user_token()

    @classmethod
    async def get_user_email_or_none(
            cls,
            email: str = Cookie("", alias="email"),
            token: str = Cookie("", alias="token"),
    ) -> str | None:

        if not token or not email:
            return None

        token_list = await AuthAdapter(email).load_user_token()
        if token in token_list:
            return email
        return None

    @classmethod
    async def login_required(
            cls,
            request: Request,
            email: str = Cookie("", alias="email"),
            token: str = Cookie("", alias="token"),
    ):
        user_email = await cls.get_user_email_or_none(email, token)
        if not user_email:
            raise ErrorWithPrompt("认证失败")
        request.state.email = user_email
