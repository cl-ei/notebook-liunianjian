import logging
import traceback

import starlette
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from src.framework import error
from fastapi.responses import JSONResponse, Response, HTMLResponse


class ErrorCatchMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        stream_resp_t = starlette.middleware.base._StreamingResponse  # noqa
        try:
            response: Optional[stream_resp_t, Response] = await call_next(request)
        except error.ErrorWithPrompt as e:
            response = JSONResponse({"code": 400, "msg": e.msg})
        except Exception as e:  # noqa
            logging.error(f"internal error: {e}\n{traceback.format_exc()}")
            response = HTMLResponse(content=f"internal error", status_code=500)

        response.headers['Server'] = 'madliar'
        return response
