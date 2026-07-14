from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from src.router import auth, editor, fs, home
from src.framework.config import DEBUG
from src.framework.midddleware import ErrorCatchMiddleware


PROJECT_NAME = "https://github.com/cl-ei/notebook-liunianjian"
VERSION = "1.0"


def get_application() -> FastAPI:
    application = FastAPI(
        title=PROJECT_NAME,
        debug=DEBUG,
        version=VERSION,
        docs_url="/notebook/docs",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(ErrorCatchMiddleware)
    application.mount("/notebook/static", StaticFiles(directory="src/static"), name="static")
    application.include_router(auth.router, prefix="", tags=["auth"])
    application.include_router(editor.router, prefix="", tags=["blog"])
    application.include_router(fs.router, prefix="", tags=["fs"])
    application.include_router(home.router, prefix="", tags=["home"])

    return application


app = get_application()
