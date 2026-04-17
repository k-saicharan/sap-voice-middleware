from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_api_key(x_api_key: str = Header(default="")) -> str:
    if not settings.API_KEYS:
        return "anonymous"
    valid_keys = {k.strip() for k in settings.API_KEYS.split(",") if k.strip()}
    if x_api_key not in valid_keys:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return x_api_key
