import re
from fastapi import APIRouter, Cookie, Depends, Body, Request
from fastapi.responses import JSONResponse, HTMLResponse
from src.operation.auth import AuthMgr
from src.framework.error import ErrorWithPrompt
from src.framework.config import DEBUG
from src.utils import render_to_html

router = APIRouter()


@router.get("/notebook/guest")
async def notebook_login() -> HTMLResponse:
    return render_to_html("src/tpl/guest.html")


@router.post("/notebook/register")
async def register(
        email: str = Body(""),
        password: str = Body(""),
):
    if not DEBUG:
        return {
            "code": 400,
            "msg": "此站点不再支持注册。你可以自行部署此网站的开源版本，具体请访问："
                   '<a href="https://github.com/cl-ei/notebook.madliar">https://github.com/cl-ei/notebook.madliar</a>'
        }

    email_pattern = re.compile(r"^[A-Za-z\d]+([-_.][A-Za-z\d]+)*@([A-Za-z\d]+[-.])+[A-Za-z\d]{2,4}$")
    if not email_pattern.match(email):
        return {"code": 403, "msg": "错误的邮箱"}

    if not 5 < len(password) < 48:
        return {"code": 403, "msg": "密码长度限定为6~47字符"}

    try:
        token = await AuthMgr.register(email, password)
    except ErrorWithPrompt as e:
        return {"code": 403, "msg": e.msg}

    resp = JSONResponse({"code": 0, "email": email})
    resp.set_cookie(key="token", value=token, httponly=True)
    resp.set_cookie(key="email", value=email, httponly=True)
    return resp


@router.post("/notebook/logout", dependencies=[Depends(AuthMgr.login_required)])
async def logout(
        request: Request,
        token: str = Cookie("", alias="token")
):

    await AuthMgr.logout(request.state.email, token)
    resp = JSONResponse({"code": 0})
    resp.delete_cookie(key="email", httponly=True)
    resp.delete_cookie(key="token", httponly=True)
    return resp


@router.post("/notebook/login")
async def login(
        email: str = Body(...),
        password: str = Body(...),
):
    email_pattern = re.compile(r"^[A-Za-z\d]+([-_.][A-Za-z\d]+)*@([A-Za-z\d]+[-.])+[A-Za-z\d]{2,4}$")
    if not email_pattern.match(email):
        return {"code": 403, "msg": u"错误的邮箱"}

    if not 5 < len(password) < 48:
        return {"code": 403, "msg": u"密码过长或过短"}

    try:
        token = await AuthMgr.login(email, password)
    except ErrorWithPrompt as e:
        return {"code": 403, "msg": e.msg}

    resp = JSONResponse({"code": 0, "msg": "ok", "data": {"email": email}})
    resp.set_cookie("email", value=email, httponly=True)
    resp.set_cookie("token", value=token, httponly=True)
    return resp


@router.post("/notebook/change_password", dependencies=[Depends(AuthMgr.login_required)])
async def change_password(
        request: Request,
        old_password: str = Body(...),
        new_password: str = Body(...),
):
    if not 5 < len(old_password) < 48 or not 5 < len(new_password) < 48:
        return {"code": 403, "msg": "email或密码错误", "data": None}

    try:
        await AuthMgr.change_password(request.state.email, old_password, new_password)
    except ErrorWithPrompt as e:
        return {"code": 403, "msg": e.msg}

    resp = JSONResponse({"code": 0, "msg": "ok", "data": None})
    resp.delete_cookie(key="email", httponly=True)
    resp.delete_cookie(key="token", httponly=True)
    return resp
