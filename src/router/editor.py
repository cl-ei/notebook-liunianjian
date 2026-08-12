import asyncio
import os
import mimetypes
from urllib.parse import unquote
from fastapi import APIRouter, Path, Cookie, Depends, Request, Body, HTTPException
from starlette.responses import Response
from starlette.status import HTTP_404_NOT_FOUND, HTTP_403_FORBIDDEN, HTTP_500_INTERNAL_SERVER_ERROR

from src import utils
from src.operation.auth import AuthMgr
from src.utils.global_lock import GlobalLock
from src.operation.site.generator import parse_user_site_config
from src.operation.guest_fs import read_guest_file, read_guest_image
from src.operation.site.generator import StaticSiteGenerator
from src.framework.error import ErrorWithPrompt
from src.framework.config import RESERVED_EMAIL
from src.storage.versioning_adaptor import (
    VersioningAdapter,
    FileOpenRespData,
    DiffItem,
)
from src.storage.user_fs_adapter import UserFSAdapter
from src.storage.share_adapter import ShareAdapter
from src.utils import render_to_html


router = APIRouter()


@router.get("/notebook/img_preview/{email_user}/{email_service}/{file:path}")
async def img_preview(
        email_user: str = Path(...),
        email_service: str = Path(...),
        file: str = Path(...),
        token: str = Cookie(""),
):
    """
    1. 校验email是否和当前用户一致
    2. 有shared key

    """
    email = f"{email_user}@{email_service}"
    if email == RESERVED_EMAIL:
        return read_guest_image("/" + file)

    login_email = await AuthMgr.get_user_email_or_none(email, token)
    if login_email != email:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    mimetype, content = await UserFSAdapter(email).get_original_image_file(file)
    if content is not None:
        return Response(content, media_type=mimetype)
    raise HTTPException(status_code=HTTP_404_NOT_FOUND)


@router.post("/notebook/open")
async def openfile(
        request: Request,
        filepath: str = Body(...),
        version: int | None = Body(None),
        email: str = Depends(AuthMgr.get_user_email_or_none),
):
    """
    前端打开文件的接口
    统一处理，尝试用 utf-8 解码文件，如果打不开则抛出异常

    Args：
        filepath : 文件相对路径（必填）
        version : 目标版本号（可选，为空时取最新版本）

    Returns：
        {"code": 0, "msg": "ok", "data": {
            version: 1,
            base: 0,
            base_content: "xxx",
            diff: [{
                count: 0,
                added: false,
                removed: false,
                value: "abcd"
            }, ...]
    """
    if email:
        fr: FileOpenRespData = await VersioningAdapter(email).open_file(filepath, version)
    else:
        fr: FileOpenRespData = read_guest_file(path=filepath)
    return {"code": 0, "msg": "ok", "data": fr.dict()}


@router.post("/notebook/save_file_delta", dependencies=[Depends(AuthMgr.login_required)])
async def save_file_delta(
        request: Request,
        filepath: str = Body(...),
        base: int = Body(...),
        dst_md5: str = Body(...),
        diff: list[DiffItem] = Body(..., default_factory=list),
):
    lock_key = f"LK:save:{request.state.email}:{utils.calc_md5(filepath)}"
    async with GlobalLock(name=lock_key, lock_time=600) as lock:
        if not lock.locked:
            raise ErrorWithPrompt("访问频繁，请稍后再试")

        vd = VersioningAdapter(request.state.email)
        version, base = await vd.save_file_delta(filepath, base, dst_md5, diff)

    return {"code": 0, "data": {"version": version, "base": base}}


@router.post("/notebook/history", dependencies=[Depends(AuthMgr.login_required)])
async def get_history(
        request: Request,
        filepath: str = Body(..., embed=True),
):
    """
    Returns: {
        "code": 0, "msg": "ok", "data": {
            "history": [{
                version: 12,
                base: 10,
                create_time: "2023-01-31 22:08:09",
                lines: 2 // 改动行数
            }, ...]
        }
    }
    """
    history = await VersioningAdapter(request.state.email).get_history(file=filepath)
    return {"code": 0, "msg": "ok", "data": {"history": history}}


@router.post("/notebook/diff", dependencies=[Depends(AuthMgr.login_required)])
async def get_diff_detail(
        request: Request,
        filepath: str = Body(...),
        version: int = Body(...),
):
    """
    获取某个版本相较于上一个版本的内容差异

    Returns: {
        "code": 0, "msg": "ok", "data": {
            prev_version: 32,
            prev_content: "not okk"
            current_version: 19,
            current_content: "okk"
        }
    }
    """
    if version < 1:
        raise ErrorWithPrompt("无更新版本")

    diff_resp = await VersioningAdapter(request.state.email).get_diff(file=filepath, version=version)
    return {"code": 0, "msg": "ok", "data": diff_resp.dict()}


@router.post("/notebook/share", dependencies=[Depends(AuthMgr.login_required)])
async def enable_share(
        request: Request,
        filepath: str = Body(..., embed=True)
):
    await ShareAdapter(request.state.email).enable_share(filepath)
    user, service = request.state.email.split("@", 1)
    return {"code": 0, "msg": "ok", "data": {"key": f"/notebook/share/{user}/{service}/{filepath.lstrip('/')}"}}


@router.delete("/notebook/share", dependencies=[Depends(AuthMgr.login_required)])
async def disable_share(
        request: Request,
        filepath: str = Body(..., embed=True),
):
    await ShareAdapter(request.state.email).disable_share(filepath)
    user, service = request.state.email.split("@", 1)
    return {"code": 0, "msg": "ok", "data": {"key": f"/notebook/share/{user}/{service}/{filepath.lstrip('/')}"}}


@router.get("/notebook/share_settings/{file:path}", dependencies=[Depends(AuthMgr.login_required)])
async def share_settings(
        request: Request,
        file: str = Path(...),
):
    """
    检查文件是否已被分享

    """
    allowed = await ShareAdapter(request.state.email).test_share(file)
    if allowed:
        return {"code": 0, "msg": "ok", "data": None}
    else:
        return {"code": 403, "msg": "forbidden", "data": None}


@router.get("/notebook/share/{email_user}/{email_service}/{file:path}")
async def share(
        email_user: str = Path(...),
        email_service: str = Path(...),
        file: str = Path(...),
):
    """
    获取分享的文件
    不管是文本文件还是媒体文件，都需要检查 meta, 创建了 shared key 才可以访问

    Params:
        test: bool 当传 "true" 时，只检测是否允许访问，返回 206
            否则返回整个页面
    """
    email = f"{email_user}@{email_service}"
    mimetype, content = await ShareAdapter(email).get_share(file)
    if mimetype.startswith("image/"):
        return Response(content, media_type=mimetype)

    _, filename = os.path.split(file)
    base_filename, ext = os.path.splitext(filename)

    context = {"title": base_filename, "content": content, "path": file}
    return render_to_html("src/tpl/share.html", context=context)


@router.post("/notebook/static_site", dependencies=[Depends(AuthMgr.login_required)])
async def gen_static_site(request: Request):
    flag, msg = await StaticSiteGenerator(request.state.email).gen()
    return {"code": 0 if flag else 400, "msg": msg or "ok", "data": None}


@router.get("/notebook/publish/{email_user}/{email_service}/{file_path:path}")
async def preview_publish(
        email_user: str = Path(...),
        email_service: str = Path(...),
        file_path: str = Path(...),
):
    """
    用户静态站点预览（完全基于 adapter.storage 接口）
    """
    email = f"{email_user}@{email_service}"
    config = await parse_user_site_config(email)

    def _normalize_path(raw: str) -> str:
        """
        规范化 URL 路径：
        - URL decode
        - 禁止路径遍历
        - 统一为正斜杠
        """
        decoded = unquote(raw)
        if ".." in decoded.split("/"):
            raise HTTPException(400, "Invalid path")
        return decoded.lstrip("/")

    adapter = UserFSAdapter(email)

    build_root = f"{adapter.storage_root}/{config.build.source_root.strip('/')}/_build"
    raw_path = _normalize_path(file_path)

    # 1. 根路径兜底
    if not raw_path:
        raw_path = "index.html"

    full_path = f"{build_root}/{raw_path}"

    # 2. 路径存在性 & 安全性检查
    if not await adapter.storage.exists(full_path):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)

    # 3. 目录 → index.html
    if await adapter.storage.is_dir(full_path):
        index_path = f"{full_path}/index.html"
        if await adapter.storage.exists(index_path) and \
                await adapter.storage.is_file(index_path):
            full_path = index_path
        else:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND)

    # 4. 非文件 → 404
    if not await adapter.storage.is_file(full_path):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)

    # 5. 读取内容
    try:
        bin_content = await adapter.storage.read_bytes(full_path)
    except Exception as e:
        raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, f"Read file failed: {e}")

    # 6. MIME 推断
    mime_type, _ = mimetypes.guess_type(full_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    # 7. 返回响应（禁用缓存，方便预览）
    return Response(
        content=bin_content,
        media_type=mime_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
