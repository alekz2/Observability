from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from remote_query_service.core.models import Actor
from remote_query_service.core.settings import Settings, get_settings


def get_actor(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Actor:
    api_keys = settings.parsed_api_keys()
    if not api_keys:
        return Actor(subject="anonymous")
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    subject = api_keys.get(token)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return Actor(subject=subject)

