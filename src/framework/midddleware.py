import re
import http
import json
import logging
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse, HTMLResponse
from src.framework import error


class ErrorCatchMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except error.ErrorWithPrompt as e:
            return self._create_error_response(request, status_code=400, message=e.msg)
        except Exception as e:
            logging.error(f"internal error: {e}\n{traceback.format_exc()}")
            return self._create_error_response(request, status_code=500, message="Internal Server Error")

        if response.status_code >= 400:
            # 尝试从原响应中提取错误信息
            message = self._extract_message(response) or http.HTTPStatus(response.status_code).phrase
            response = self._create_error_response(request, status_code=response.status_code, message=message)

        return response

    @staticmethod
    def _extract_message(response) -> str | None:
        """从已有响应中提取错误信息（兼容 JSON / HTML）"""
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                body = b"".join(response.body_iterator).decode("utf-8")
                data = json.loads(body)
                return data.get("detail") or data.get("msg")
            except:  # noqa
                return None

        if "text/html" in content_type:
            try:
                body = b"".join(response.body_iterator).decode("utf-8")
                # 简单粗暴：取 <p> 标签内容
                m = re.search(r"<p>(.*?)</p>", body)
                if m:
                    return m.group(1)
            except:  # noqa
                pass

        return None

    @staticmethod
    def _wants_json(request: Request) -> bool:
        """判断客户端是否偏好 JSON 响应"""
        accept = request.headers.get("accept", "")
        # 明确要 JSON 就返回 JSON
        if "application/json" in accept:
            return True
        # 明确要 HTML 就返回 HTML
        if "text/html" in accept:
            return False
        # 都没明确指定时的默认策略：对 API 服务来说，默认 JSON 更友好
        return True

    def _create_error_response(self, request: Request, status_code: int, message: str):
        if self._wants_json(request):
            return JSONResponse(
                status_code=status_code,
                content={"code": status_code, "msg": message}
            )

        # 获取标准的 HTTP 状态短语
        status_phrase = http.HTTPStatus(status_code).phrase

        html = (
            f"<!DOCTYPE html>"
            f"<html>"
            f"<head><title>{status_code} {status_phrase}</title></head>"
            f"<body><h1>{status_code} {status_phrase}</h1><p>{message}</p></body>"
            f"</html>"
        )
        return HTMLResponse(status_code=status_code, content=html)
