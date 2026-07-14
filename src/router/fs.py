import os.path
import time

from fastapi import APIRouter, Request, File, Form, UploadFile, Depends, Body
from fastapi.responses import JSONResponse
from src.operation.auth import AuthMgr
from src.storage.user_fs_adapter import UserFSAdapter
from src.framework.error import ErrorWithPrompt


router = APIRouter()


@router.post("/notebook/upload", dependencies=[Depends(AuthMgr.login_required)])
async def upload(
        request: Request,
        file: UploadFile = File(...),
        path: str = Form(..., alias="node_id"),
):
    if file.size > 1024*1024*5:
        return {"code": 400, "msg": "文件过大，最大支持5MB"}

    save_path = os.path.join(path.lstrip("/"), file.filename)
    content: bytes = await file.read(1024*1024*25)
    await UserFSAdapter(request.state.email).create_file(save_path, content)
    return {"code": 0, "msg": "ok"}


@router.post("/notebook/listdir", dependencies=[Depends(AuthMgr.login_required)])
async def listdir(
        request: Request,
        path: str = Body(..., embed=True),
):
    """
    返回路径下的项目：

    Returns:
        code: int, 0
        msg: str, "ok"
        data: list, eg: [{
            "id": "/root",
            "type": "dir",  // or "file"
            "text": "root",  // 实际为 display name
        }, ...]
    """
    if path == "#":
        files = [{"id": "/", "type": "dir", "text": "/"}]
    else:
        data = await UserFSAdapter(request.state.email).ls(path)
        files = [f.dict() for f in data]
    return {
        "code": 0,
        "msg": "ok",
        "data": files,
    }


@router.post("/notebook/mkdir", dependencies=[Depends(AuthMgr.login_required)])
async def mkdir(
        request: Request,
        node_id: str = Body(...),
        dir_name: str = Body(...),
):
    try:
        rel_path = os.path.join(node_id, dir_name)
        await UserFSAdapter(request.state.email).mkdir(rel_path)
    except ErrorWithPrompt as e:
        return {"code": 403, "msg": e.msg}
    return {"code": 0, "msg": "ok"}


@router.post("/notebook/rm", dependencies=[Depends(AuthMgr.login_required)])
async def rm(
        request: Request,
        node_id: str = Body(..., embed=True),
):
    if node_id.strip() == "/":
        raise ErrorWithPrompt("禁止删除根目录")

    await UserFSAdapter(request.state.email).rm(node_id)
    return {"code": 0, "msg": "ok"}


@router.post("/notebook/rename", dependencies=[Depends(AuthMgr.login_required)])
async def rename(
        request: Request,
        node_id: str = Body(...),
        new_name: str = Body(...),
):
    if "/" in new_name or "\\" in new_name:
        raise ErrorWithPrompt("新路径名不可包含特殊字符")

    await UserFSAdapter(request.state.email).rename(node_id, new_name)
    return {"code": 0, "msg": "ok"}


@router.post("/notebook/new", dependencies=[Depends(AuthMgr.login_required)])
async def newfile(
        request: Request,
        node_id: str = Body(...),
        file_name: str = Body(...),
):
    file = os.path.join(node_id, file_name)
    try:
        await UserFSAdapter(request.state.email).create_file(file=file)
    except ErrorWithPrompt as e:
        return {"code": 400, "msg": e.msg}
    return {"code": 0, "msg": "ok"}


@router.post("/notebook/mv", dependencies=[Depends(AuthMgr.login_required)])
async def move(
        request: Request,
        src: str = Body(...),
        dst: str = Body(...),
):
    try:
        await UserFSAdapter(request.state.email).move(src=src, dst=dst)
    except ErrorWithPrompt as e:
        return {"code": 400, "msg": e.msg}
    return {"code": 0, "msg": "ok"}
