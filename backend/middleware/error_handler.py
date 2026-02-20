from fastapi import Request
from fastapi.responses import JSONResponse
from backend.exceptions import AppError

async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.code, content={"error": exc.msg, "success": False})

async def unhandled_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "Internal server error", "success": False})
