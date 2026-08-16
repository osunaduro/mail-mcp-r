"""Servidor MCP en transporte HTTP/OAuth para el dominio de correo."""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlsplit, urlunsplit

from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.server.auth.routes import create_protected_resource_routes
from starlette.middleware import Middleware

from mcp_server.auth import BearerTokenMiddleware
from mcp_server.config import (
    AUTH_MODE,
    MEKA_API_KEY,
    MEKA_OIDC_AUDIENCE,
    MEKA_OIDC_ISSUER,
    MEKA_OIDC_JWKS_URL,
    MEKA_OIDC_RESOURCE_URL,
)
from mcp_server.tools import INSTRUCTIONS, SUPPORTED_SCOPES, register_tools

__all__ = ["app", "mcp"]


class OIDCResourceServer(RemoteAuthProvider):
    """Anuncia todos los scopes de herramientas sin exigirlos todos en cada request."""

    def get_routes(self, mcp_path: str | None = None):
        resource_url = self._get_resource_url(mcp_path)
        if resource_url is None:
            return []
        return create_protected_resource_routes(
            resource_url=resource_url,
            authorization_servers=self.authorization_servers,
            scopes_supported=SUPPORTED_SCOPES,
            resource_name=self.resource_name,
            resource_documentation=self.resource_documentation,
        )


def _required_oidc_value(name: str, value: str | None) -> str:
    if value:
        return value
    raise ValueError(f"{name} must be configured when MEKA_AUTH_MODE=oidc.")


def _oidc_resource_location() -> tuple[str, str]:
    resource_url = _required_oidc_value("MEKA_OIDC_RESOURCE_URL", MEKA_OIDC_RESOURCE_URL)
    parsed = urlsplit(resource_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MEKA_OIDC_RESOURCE_URL must be an absolute HTTP(S) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("MEKA_OIDC_RESOURCE_URL must not contain a query string or fragment.")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")), parsed.path.rstrip("/") or "/"


def _oidc_auth_provider() -> tuple[OIDCResourceServer, str]:
    issuer = _required_oidc_value("MEKA_OIDC_ISSUER", MEKA_OIDC_ISSUER)
    audience = _required_oidc_value("MEKA_OIDC_AUDIENCE", MEKA_OIDC_AUDIENCE)
    jwks_url = _required_oidc_value("MEKA_OIDC_JWKS_URL", MEKA_OIDC_JWKS_URL)
    base_url, mcp_path = _oidc_resource_location()
    verifier = JWTVerifier(jwks_uri=jwks_url, issuer=issuer, audience=audience)
    return (
        OIDCResourceServer(
            token_verifier=verifier,
            authorization_servers=[issuer],
            base_url=base_url,
            resource_name="MEKA Mail",
        ),
        mcp_path,
    )


def _scope(scope: str):
    """Exige un scope OAuth mientras el servidor corre en modo OIDC."""

    def decorate(function):
        if AUTH_MODE != "oidc":
            return function

        @wraps(function)
        def guarded(*args, **kwargs):
            token = get_access_token()
            if token is None or scope not in token.scopes:
                raise PermissionError(f"Missing required OAuth scope: {scope}")
            return function(*args, **kwargs)

        return guarded

    return decorate


mcp_auth, mcp_path = _oidc_auth_provider() if AUTH_MODE == "oidc" else (None, None)

mcp = FastMCP("mail-mcp", instructions=INSTRUCTIONS, auth=mcp_auth)

register_tools(mcp, scope_guard=_scope if AUTH_MODE == "oidc" else None)

http_middleware = (
    [Middleware(BearerTokenMiddleware, token=MEKA_API_KEY)] if AUTH_MODE == "api-key" else []
)
app = mcp.http_app(path=mcp_path, middleware=http_middleware)
