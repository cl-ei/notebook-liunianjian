from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse, Response
from src.operation.auth import AuthMgr
from src.utils import render_to_html


router = APIRouter()


@router.get("/")
async def homepage() -> RedirectResponse:
    return RedirectResponse(url="/notebook/publish/t/t.tt/index.html")


@router.get("/notebook")
async def notebook_home(
        email: str = Depends(AuthMgr.get_user_email_or_none)
):
    if not email:
        return RedirectResponse(url="/notebook/guest")
    return render_to_html(
        tpl="src/tpl/home.html",
        context={"login_info": {"email": email}}
    )
