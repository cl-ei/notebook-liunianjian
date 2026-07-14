import os
import time

from fastapi import APIRouter, Path, Cookie, Depends, Request, Body
from fastapi.responses import Response

from src import utils
from src.operation.auth import AuthMgr
from src.utils.global_lock import GlobalLock
from src.operation import worker
from src.framework.error import ErrorWithPrompt
from src.storage.versioning_adaptor import (
    VersioningAdapter,
    FileOpenRespData,
    DiffItem,
)
from src.storage.blog_adapter import BlogAdapter
from src.storage.user_fs_adapter import UserFSAdapter
from src.storage.share_adapter import ShareAdapter
from src.framework.error import Forbidden, NotFound
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
    login_email = await AuthMgr.get_user_email_or_none(email, token)
    if login_email != email:
        raise Forbidden()

    mimetype, content = await UserFSAdapter(email).get_original_image_file(file)
    if content is not None:
        return Response(content, media_type=mimetype)
    raise NotFound()


@router.post("/notebook/open", dependencies=[Depends(AuthMgr.login_required)])
async def openfile(
        request: Request,
        filepath: str = Body(...),
        version: int | None = Body(None),
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

    fr: FileOpenRespData = await VersioningAdapter(request.state.email).open_file(filepath, version)
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


@router.post("/notebook/blog/publish", dependencies=[Depends(AuthMgr.login_required)])
async def blog_publish(request: Request):
    email = request.state.email
    version = f"{time.time()}"

    worker.create_task_publish_blog(email=email, version=version)
    return {"code": 0, "msg": "ok", "data": {"version": version}}


@router.get("/notebook/blog", dependencies=[Depends(AuthMgr.login_required)])
async def get_blog_info(request: Request):
    version = await BlogAdapter(request.state.email).get_version()
    return {"code": 0, "msg": "ok", "data": {"version": version}}
