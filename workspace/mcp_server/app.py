"""Punto de entrada de producción: combina el servidor MCP y la API REST.

Ambas apps comparten el mismo ``MailService`` (``mcp_server.service.get_service``)
y corren en el mismo proceso/contenedor — evita duplicar infraestructura (otro
host de proxy, otro DNS) para el mismo backend. El montaje de ``/api/v1`` va
antes que el de ``/`` porque un ``Mount("/")`` matchea cualquier prefijo: si
quedara primero, interceptaría también los pedidos a la API REST.

El ``lifespan`` de ``mcp_app`` se propaga al Starlette padre a propósito: es
quien arranca el ``StreamableHTTPSessionManager`` interno de FastMCP (su
task group). Sin esto, toda request al MCP monta un ``RuntimeError`` en
tiempo de ejecución ("task group was not initialized") aunque el ruteo esté
bien — FastMCP documenta este requisito para montarlo dentro de otra app ASGI.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp_server.http import app as mcp_app
from mcp_server.rest_api import app as rest_api_app

__all__ = ["app"]

app = Starlette(
    routes=[
        Mount("/api/v1", app=rest_api_app),
        Mount("/", app=mcp_app),
    ],
    lifespan=mcp_app.lifespan,
)
