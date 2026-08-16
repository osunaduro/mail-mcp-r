"""Variables de entorno que controlan el transporte del servidor MCP.

No define nada relativo al dominio de correo (eso es exclusivo de
``mail_core``); sólo lee configuración de transporte/autenticación.
"""

from __future__ import annotations

import os

AUTH_MODE = os.environ.get("MEKA_AUTH_MODE", "oidc")

MEKA_API_KEY = os.environ.get("MEKA_API_KEY", "")

MEKA_OIDC_ISSUER = os.environ.get("MEKA_OIDC_ISSUER", "")
MEKA_OIDC_AUDIENCE = os.environ.get("MEKA_OIDC_AUDIENCE", "")
MEKA_OIDC_JWKS_URL = os.environ.get("MEKA_OIDC_JWKS_URL", "")
MEKA_OIDC_RESOURCE_URL = os.environ.get("MEKA_OIDC_RESOURCE_URL", "")
