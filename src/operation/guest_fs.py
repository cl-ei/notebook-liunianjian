import os
import mimetypes
from pathlib import Path
from fastapi.responses import Response
from fastapi.exceptions import HTTPException
from src.framework.error import ErrorWithPrompt
from src.storage.versioning_adaptor import FileOpenRespData


VALID_ROOT_OBJ = (
    "/",
    "/guest",
    "/README.md",
    "/_site_config.example.yaml",
)


def resolve_path(path: str) -> str:
    if path.startswith("/guest/"):
        pass
    elif path in VALID_ROOT_OBJ:
        pass
    else:
        raise ErrorWithPrompt("错误的路径1")

    root_path = os.getcwd()
    root = Path(root_path)

    rel_path = path.lstrip("/")
    real_path = (root_path / Path(rel_path)).resolve()
    # 防止 ../.. 逃逸
    if not real_path.is_relative_to(root):
        raise ErrorWithPrompt("错误的路径2")

    return str(real_path)


def list_guest_fs(path: str) -> list[dict]:
    """

    Returns:
        list of dict: {
            "id": "/",
            "type": "dir",
            "text": "/",
        }
    """
    search_path = resolve_path(path)
    result = []

    for filelike in os.listdir(search_path):
        display_path = os.path.join("/", path.lstrip('/'), filelike).replace("\\", "/")
        if path == "/" and display_path not in VALID_ROOT_OBJ:
            continue

        full_path = os.path.join(search_path, filelike)
        if os.path.isdir(full_path):
            result.append({"id": display_path, "type": "dir", "text": filelike})
        elif os.path.isfile(full_path):
            result.append({"id": display_path, "type": "file", "text": filelike})

    result.sort(key=lambda x: (x['type'], x['text']))
    return result


def read_guest_file(path: str) -> FileOpenRespData:
    full_path = resolve_path(path)
    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return FileOpenRespData(version=0, base=0, base_content=content, diff=[])


def read_guest_image(path: str) -> Response:
    full_path = resolve_path(path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404)

    mimetype = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
    if not isinstance(mimetype, str) or not mimetype.startswith("image/"):
        raise HTTPException(status_code=404)
    with open(full_path, "rb") as f:
        content = f.read()

    return Response(content, media_type=mimetype)
