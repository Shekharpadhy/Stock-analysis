from pydantic import BaseModel
from datetime import datetime

class BaseResponse(BaseModel):
    success: bool = True
    message: str = "OK"

class ErrorResponse(BaseResponse):
    success: bool = False
    error: str = ""
    details: dict = {}
