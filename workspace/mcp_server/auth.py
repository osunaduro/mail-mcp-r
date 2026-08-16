"""Middleware de autenticación por Bearer token estático.

Compartido por el transporte HTTP del MCP (modo ``api-key``, token
``MEKA_API_KEY``) y por la API REST (token ``MAIL_SERVICE_TOKEN``) — misma
lógica de verificación, cada uno con su propio secreto independiente.
"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Rechaza toda solicitud que no traiga el bearer token configurado."""

    def __init__(self, app, *, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._token:
            return JSONResponse(
                {"error": "Server authentication is not configured."}, status_code=503
            )
        scheme, _, supplied_token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            supplied_token, self._token
        ):
            return JSONResponse({"error": "Unauthorized."}, status_code=401)
        return await call_next(request)
