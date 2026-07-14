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
            if response.status_code == 404:
                raise error.NotFound
        except error.ErrorWithPrompt as e:
            return JSONResponse({"code": 400, "msg": e.msg})
        except error.NotFound:
            return HTMLResponse(content="<center><h1>404 - Not Found</h1></center>", status_code=404)
        except error.Forbidden:
            return HTMLResponse(content="<center><h1>403 - Forbidden</h1></center>", status_code=403)
        except Exception as e:  # noqa
            logging.error(f"internal error: {e}\n{traceback.format_exc()}")
            return HTMLResponse(content=f"internal error", status_code=500)

        if response.status_code >= 400:
            origin_err = []
            async for content in response.body_iterator:
                origin_err.append(content.decode("utf-8", errors="ignore"))
            return JSONResponse({"code": response.status_code, "msg": "".join(origin_err)})

        response.headers['Server'] = 'madliar'
        return response
