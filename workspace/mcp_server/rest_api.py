"""API REST plana sobre ``mail_core``, para consumidores servicio-a-servicio.

Distinta filosofía que ``mcp_server/tools.py``: acá no hay protocolo MCP,
solo HTTP + JSON con status codes estándar. Pensada para automatizaciones
del ecosistema (ej. ``wp-forwarder``, que procesa correos entrantes) que
necesitan operar sobre las cuentas de correo sin hablar MCP.

``mail-mcp-r`` es un servicio del ecosistema, no una librería para importar
en cada proyecto: si mañana cambia el backend de correo (otro proveedor,
otra biblioteca), los consumidores de esta API no se enteran — solo hablan
HTTP contra rutas estables.

Expone las mismas operaciones que ``tools.py`` (mismo ``MailService``), con
un contrato HTTP idiomático en vez del envelope MCP `{"ok":...,"result":...}`:
errores como status code + `{"error": ...}`, y adjuntos descargados como
binario crudo en vez de JSON+base64.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mail_core import (
    AccountNotFoundError,
    AuthenticationError,
    ConfigError,
    FolderNotFoundError,
    MailCoreError,
    MailConnectionError,
    MessageNotFoundError,
    ProviderError,
    SendError,
)
from mail_core.errors import AttachmentNotFoundError
from mcp_server.auth import BearerTokenMiddleware
from mcp_server.config import MAIL_SERVICE_TOKEN
from mcp_server.service import get_service

logger = logging.getLogger(__name__)

__all__ = ["app"]

_NOT_FOUND = (AccountNotFoundError, FolderNotFoundError, MessageNotFoundError, AttachmentNotFoundError)
_UPSTREAM = (AuthenticationError, MailConnectionError, SendError, ProviderError)


# ==========================================================================
# Helpers
# ==========================================================================

async def _call(fn: Callable[[], Any]) -> JSONResponse:
    """Corre ``fn`` (una llamada a MailService) en un thread y mapea errores.

    Las llamadas IMAP/SMTP son sincrónicas y bloqueantes; a diferencia del
    MCP (una tool call a la vez desde un cliente), esta API puede recibir
    pedidos concurrentes de automatizaciones, así que no deben bloquear el
    loop de eventos.
    """
    try:
        result = await anyio.to_thread.run_sync(fn)
    except _NOT_FOUND as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except _UPSTREAM as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except ConfigError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    except MailCoreError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except (KeyError, TypeError, ValueError) as exc:
        return JSONResponse({"error": f"Bad request: {exc}"}, status_code=400)
    except Exception:
        logger.exception("Unhandled error in REST API call.")
        return JSONResponse({"error": "Internal server error."}, status_code=500)

    if result is None:
        return JSONResponse({"ok": True})
    return JSONResponse(result)


async def _body(request: Request) -> dict[str, Any]:
    if not await request.body():
        return {}
    return await request.json()


def _query_int(request: Request, name: str, default: int) -> int:
    value = request.query_params.get(name)
    return int(value) if value is not None else default


# ==========================================================================
# Cuentas
# ==========================================================================

async def list_accounts(request: Request) -> JSONResponse:
    return await _call(lambda: [a.to_dict() for a in get_service().list_accounts()])


async def get_account(request: Request) -> JSONResponse:
    alias = request.path_params["alias"]
    return await _call(lambda: get_service().get_account(alias))


# ==========================================================================
# Carpetas
# ==========================================================================

async def list_folders(request: Request) -> JSONResponse:
    alias = request.path_params["alias"]
    return await _call(lambda: get_service().list_folders(alias))


async def create_folder(request: Request) -> JSONResponse:
    alias = request.path_params["alias"]
    body = await _body(request)
    return await _call(lambda: get_service().create_folder(alias, body["name"]))


async def rename_folder(request: Request) -> JSONResponse:
    alias, folder_id = request.path_params["alias"], request.path_params["folder_id"]
    body = await _body(request)
    return await _call(lambda: get_service().rename_folder(alias, folder_id, body["new_name"]))


async def delete_folder(request: Request) -> JSONResponse:
    alias, folder_id = request.path_params["alias"], request.path_params["folder_id"]
    return await _call(lambda: get_service().delete_folder(alias, folder_id))


# ==========================================================================
# Mensajes
# ==========================================================================

async def list_messages(request: Request) -> JSONResponse:
    alias, folder_id = request.path_params["alias"], request.path_params["folder_id"]
    limit = _query_int(request, "limit", 50)
    offset = _query_int(request, "offset", 0)
    return await _call(lambda: get_service().list_messages(alias, folder_id, limit, offset))


async def get_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    return await _call(lambda: get_service().get_message(alias, folder_id, message_id))


async def search_messages(request: Request) -> JSONResponse:
    alias, folder_id = request.path_params["alias"], request.path_params["folder_id"]
    query = request.query_params.get("q", "")
    limit = _query_int(request, "limit", 50)
    return await _call(lambda: get_service().search_messages(alias, folder_id, query, limit))


async def move_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().move_message(alias, folder_id, message_id, body["dest_folder_id"])
    )


async def copy_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().copy_message(alias, folder_id, message_id, body["dest_folder_id"])
    )


async def delete_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    return await _call(lambda: get_service().delete_message(alias, folder_id, message_id))


async def mark_read(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().mark_read(alias, folder_id, message_id, body.get("read", True))
    )


async def mark_flagged(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().mark_flagged(alias, folder_id, message_id, body.get("flagged", True))
    )


# ==========================================================================
# Envío
# ==========================================================================

async def send_message(request: Request) -> JSONResponse:
    alias = request.path_params["alias"]
    body = await _body(request)
    return await _call(
        lambda: get_service().send(
            alias,
            to=body["to"],
            subject=body.get("subject", ""),
            body_text=body.get("body_text"),
            body_html=body.get("body_html"),
            cc=body.get("cc"),
            bcc=body.get("bcc"),
            attachments=body.get("attachments"),
        )
    )


async def reply_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().reply(
            alias,
            folder_id,
            message_id,
            body["body_text"],
            reply_all=body.get("reply_all", False),
            include_original=body.get("include_original", True),
        )
    )


async def forward_message(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().forward(
            alias, folder_id, message_id, body["recipients"], body["body_text"]
        )
    )


async def forward_message_raw(request: Request) -> JSONResponse:
    """Reenvía el mensaje sin reconstruirlo (headers Resent-*, ver mail_core.providers.imap_smtp)."""
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    body = await _body(request)
    return await _call(
        lambda: get_service().forward_raw(alias, folder_id, message_id, body["recipients"])
    )


async def save_draft(request: Request) -> JSONResponse:
    alias = request.path_params["alias"]
    body = await _body(request)
    return await _call(
        lambda: get_service().save_draft(
            alias,
            recipients=body["recipients"],
            subject=body.get("subject", ""),
            body_text=body.get("body_text"),
            body_html=body.get("body_html"),
            cc=body.get("cc"),
            bcc=body.get("bcc"),
        )
    )


# ==========================================================================
# Adjuntos
# ==========================================================================

async def list_attachments(request: Request) -> JSONResponse:
    alias, folder_id, message_id = (
        request.path_params["alias"], request.path_params["folder_id"], request.path_params["message_id"]
    )
    return await _call(lambda: get_service().list_attachments(alias, folder_id, message_id))


async def download_attachment(request: Request) -> Response:
    alias, folder_id, message_id, attachment_id = (
        request.path_params["alias"],
        request.path_params["folder_id"],
        request.path_params["message_id"],
        request.path_params["attachment_id"],
    )
    try:
        attachment = await anyio.to_thread.run_sync(
            lambda: get_service().download_attachment(alias, folder_id, message_id, attachment_id)
        )
    except _NOT_FOUND as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except _UPSTREAM as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except MailCoreError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        logger.exception("Unhandled error downloading attachment.")
        return JSONResponse({"error": "Internal server error."}, status_code=500)

    data = attachment.get("data") or b""
    content_type = attachment.get("content_type") or "application/octet-stream"
    filename = attachment.get("filename") or "attachment"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==========================================================================
# Rutas
# ==========================================================================

routes = [
    Route("/accounts", list_accounts, methods=["GET"]),
    Route("/accounts/{alias}", get_account, methods=["GET"]),
    Route("/accounts/{alias}/folders", list_folders, methods=["GET"]),
    Route("/accounts/{alias}/folders", create_folder, methods=["POST"]),
    Route("/accounts/{alias}/folders/{folder_id}", rename_folder, methods=["PATCH"]),
    Route("/accounts/{alias}/folders/{folder_id}", delete_folder, methods=["DELETE"]),
    Route("/accounts/{alias}/folders/{folder_id}/messages", list_messages, methods=["GET"]),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/search", search_messages, methods=["GET"]
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}", get_message, methods=["GET"]
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}",
        delete_message,
        methods=["DELETE"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/move",
        move_message,
        methods=["POST"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/copy",
        copy_message,
        methods=["POST"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/read",
        mark_read,
        methods=["POST"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/flag",
        mark_flagged,
        methods=["POST"],
    ),
    Route("/accounts/{alias}/messages/send", send_message, methods=["POST"]),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/reply",
        reply_message,
        methods=["POST"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/forward",
        forward_message,
        methods=["POST"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/forward-raw",
        forward_message_raw,
        methods=["POST"],
    ),
    Route("/accounts/{alias}/drafts", save_draft, methods=["POST"]),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/attachments",
        list_attachments,
        methods=["GET"],
    ),
    Route(
        "/accounts/{alias}/folders/{folder_id}/messages/{message_id}/attachments/{attachment_id}",
        download_attachment,
        methods=["GET"],
    ),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(BearerTokenMiddleware, token=MAIL_SERVICE_TOKEN)],
)
