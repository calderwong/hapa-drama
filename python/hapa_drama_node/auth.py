from __future__ import annotations

from fastapi import HTTPException, Request

from .config import env_truthy


def verify_request_token(request: Request, expected_token: str) -> None:
    token: str | None = None
    auth = request.headers.get("authorization")
    if auth:
        parts = auth.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    allow_query = env_truthy(request.app.state.allow_query_token)
    if token is None and allow_query:
        token = request.query_params.get("token")
    if not token or token != expected_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
