from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.auth import verify_token
from backend.database.db import get_db

security = HTTPBearer()

async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = verify_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

__all__ = ["get_db", "get_current_user"]
