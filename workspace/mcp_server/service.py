"""Acceso compartido a ``MailService`` entre transportes.

Tanto las herramientas MCP (``tools.py``) como la API REST (``rest_api.py``)
necesitan el mismo ``MailService``, resuelto desde el mismo archivo de
cuentas. Esta es la única fuente de verdad para esa resolución — evita que
cada transporte defina su propio singleton y su propia lectura de
``MAIL_MCP_CONFIG``.
"""

from __future__ import annotations

import os

from mail_core import MailService

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "home", "config", "accounts.yaml"
)

_service: MailService | None = None


def get_service() -> MailService:
    global _service
    if _service is None:
        config_path = os.environ.get("MAIL_MCP_CONFIG", DEFAULT_CONFIG_PATH)
        _service = MailService(config_path)
    return _service
