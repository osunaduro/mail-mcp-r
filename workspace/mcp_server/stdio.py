"""Servidor MCP en transporte STDIO para el dominio de correo.

Transporte local para clientes como Claude Desktop, VS Code, Cursor o
Windsurf. Reutiliza exactamente las mismas herramientas que el adaptador
HTTP, respaldadas por la misma ``mail_core``, pero no expone red: la
comunicación ocurre por stdin/stdout vía ``command`` + ``args``.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastmcp import FastMCP  # noqa: E402

from mcp_server.tools import INSTRUCTIONS, register_tools  # noqa: E402

__all__ = ["mcp", "main"]


def build_server() -> FastMCP:
    server = FastMCP("mail-mcp", instructions=INSTRUCTIONS)
    register_tools(server)
    return server


mcp = build_server()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
