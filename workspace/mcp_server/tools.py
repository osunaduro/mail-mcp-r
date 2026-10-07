"""Definición compartida de las herramientas MCP del dominio de correo.

Este módulo es la única fuente de verdad para las herramientas expuestas por
los transportes HTTP y STDIO. Cuestiones de transporte (autenticación,
ruteo, exigencia de scopes) las inyecta el servidor que llama a
``register_tools``; nunca se definen acá.

Su única responsabilidad es: validar parámetros, invocar ``mail_core`` y
devolver el resultado. No implementa lógica de negocio ni accede
directamente a la configuración.
"""

from __future__ import annotations

import base64
from typing import Any, Callable

from fastmcp import FastMCP

from mail_core import MailCoreError
from mcp_server.service import get_service as _get_service

READ_SCOPE = "mail:read"
WRITE_SCOPE = "mail:write"
DELETE_SCOPE = "mail:delete"
SUPPORTED_SCOPES = [READ_SCOPE, WRITE_SCOPE, DELETE_SCOPE]

INSTRUCTIONS = (
    "Gestiona cuentas de correo configuradas por el administrador: carpetas, mensajes, "
    "envío y adjuntos. No permite crear cuentas, cambiar credenciales ni administrar "
    "proveedores — eso es responsabilidad exclusiva del administrador del sistema. "
    "send_message, reply_message y forward_message ENVÍAN de inmediato (y guardan copia "
    "en Enviados). Para preparar un correo o una respuesta SIN enviarla, usar save_draft "
    "o save_reply_draft: quedan en la carpeta de Borradores para que una persona los "
    "revise y envíe."
)


def _ok(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": result}


def _err(exc: MailCoreError) -> dict[str, Any]:
    return {"ok": False, "error": exc.__class__.__name__, "message": str(exc)}


def register_tools(mcp: FastMCP, *, scope_guard: Callable[[str], Callable] | None = None) -> None:
    """Registra todas las herramientas de correo en ``mcp``.

    ``scope_guard`` es una factory opcional que recibe un nombre de scope y
    devuelve un decorador que lo exige. Sólo la provee el transporte HTTP en
    modo OIDC; STDIO y el modo api-key pasan ``None``.
    """

    def scoped(scope: str):
        if scope_guard is None:
            return lambda function: function
        return scope_guard(scope)

    # ------------------------------------------------------------------
    # Gestión de cuentas
    # ------------------------------------------------------------------

    @mcp.tool
    @scoped(READ_SCOPE)
    def list_accounts() -> dict[str, Any]:
        """Lista las cuentas de correo configuradas por el administrador."""
        try:
            return _ok([a.to_dict() for a in _get_service().list_accounts()])
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(READ_SCOPE)
    def get_account(alias: str) -> dict[str, Any]:
        """Consulta la información pública de una cuenta identificada por su alias."""
        try:
            return _ok(_get_service().get_account(alias))
        except MailCoreError as exc:
            return _err(exc)

    # ------------------------------------------------------------------
    # Gestión de carpetas
    # ------------------------------------------------------------------

    @mcp.tool
    @scoped(READ_SCOPE)
    def list_folders(alias: str) -> dict[str, Any]:
        """Lista las carpetas de una cuenta de correo."""
        try:
            return _ok(_get_service().list_folders(alias))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def create_folder(alias: str, name: str) -> dict[str, Any]:
        """Crea una carpeta nueva en una cuenta de correo."""
        try:
            return _ok(_get_service().create_folder(alias, name))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def rename_folder(alias: str, folder_id: str, new_name: str) -> dict[str, Any]:
        """Renombra una carpeta existente."""
        try:
            return _ok(_get_service().rename_folder(alias, folder_id, new_name))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(DELETE_SCOPE)
    def delete_folder(alias: str, folder_id: str) -> dict[str, Any]:
        """Elimina una carpeta existente."""
        try:
            _get_service().delete_folder(alias, folder_id)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    # ------------------------------------------------------------------
    # Gestión de mensajes
    # ------------------------------------------------------------------

    @mcp.tool
    @scoped(READ_SCOPE)
    def list_messages(alias: str, folder_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Lista los mensajes de una carpeta (sin cuerpo)."""
        try:
            return _ok(_get_service().list_messages(alias, folder_id, limit, offset))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(READ_SCOPE)
    def get_message(alias: str, folder_id: str, message_id: str) -> dict[str, Any]:
        """Lee el contenido completo de un mensaje."""
        try:
            return _ok(_get_service().get_message(alias, folder_id, message_id))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(READ_SCOPE)
    def search_messages(alias: str, folder_id: str, query: str, limit: int = 50) -> dict[str, Any]:
        """Busca mensajes por asunto en una carpeta."""
        try:
            return _ok(_get_service().search_messages(alias, folder_id, query, limit))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def move_message(alias: str, folder_id: str, message_id: str, dest_folder_id: str) -> dict[str, Any]:
        """Mueve un mensaje a otra carpeta."""
        try:
            _get_service().move_message(alias, folder_id, message_id, dest_folder_id)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def copy_message(alias: str, folder_id: str, message_id: str, dest_folder_id: str) -> dict[str, Any]:
        """Copia un mensaje a otra carpeta."""
        try:
            _get_service().copy_message(alias, folder_id, message_id, dest_folder_id)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(DELETE_SCOPE)
    def delete_message(alias: str, folder_id: str, message_id: str) -> dict[str, Any]:
        """Elimina un mensaje."""
        try:
            _get_service().delete_message(alias, folder_id, message_id)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def mark_read(alias: str, folder_id: str, message_id: str, read: bool = True) -> dict[str, Any]:
        """Marca un mensaje como leído (read=True) o no leído (read=False)."""
        try:
            _get_service().mark_read(alias, folder_id, message_id, read)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def mark_flagged(alias: str, folder_id: str, message_id: str, flagged: bool = True) -> dict[str, Any]:
        """Marca un mensaje como destacado (flagged=True) o no destacado."""
        try:
            _get_service().mark_flagged(alias, folder_id, message_id, flagged)
            return _ok(None)
        except MailCoreError as exc:
            return _err(exc)

    # ------------------------------------------------------------------
    # Envío
    # ------------------------------------------------------------------

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def send_message(
        alias: str,
        to: list[dict[str, Any]],
        subject: str = "",
        body_text: str = "",
        body_html: str | None = None,
        cc: list[dict[str, Any]] | None = None,
        bcc: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """ENVÍA un mensaje de correo de inmediato y guarda una copia en Enviados.

        Si el usuario pide dejarlo en borrador, NO usar esta herramienta: usar
        save_draft.

        `to`/`cc`/`bcc`: listas de {"email": str, "name": str|null}.
        `attachments`: listas de {"filename": str, "data": bytes|str, "content_type": str|null}.
        """
        try:
            result = _get_service().send(
                alias,
                to=to,
                subject=subject,
                body_text=body_text or None,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
            )
            return _ok(result)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def reply_message(
        alias: str,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> dict[str, Any]:
        """ENVÍA de inmediato una respuesta a un mensaje existente y guarda una
        copia en Enviados.

        Si el usuario pide preparar/redactar la respuesta o dejarla en
        borrador, NO usar esta herramienta: usar save_reply_draft.
        """
        try:
            result = _get_service().reply(
                alias, folder_id, message_id, body_text,
                reply_all=reply_all, include_original=include_original,
            )
            return _ok(result)
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def save_reply_draft(
        alias: str,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> dict[str, Any]:
        """Prepara una respuesta a un mensaje existente y la guarda en la
        carpeta de Borradores SIN ENVIARLA (destinatarios, asunto "Re:" y
        encadenamiento con el original se arman solos).

        Devuelve la carpeta de borradores y el UID del borrador.
        """
        try:
            return _ok(_get_service().save_reply_draft(
                alias, folder_id, message_id, body_text,
                reply_all=reply_all, include_original=include_original,
            ))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def forward_message(
        alias: str, folder_id: str, message_id: str, recipients: list[str], body_text: str
    ) -> dict[str, Any]:
        """ENVÍA de inmediato el reenvío de un mensaje a uno o más destinatarios
        (direcciones de email) y guarda una copia en Enviados."""
        try:
            return _ok(_get_service().forward(alias, folder_id, message_id, recipients, body_text))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def forward_message_raw(
        alias: str, folder_id: str, message_id: str, recipients: list[str]
    ) -> dict[str, Any]:
        """Reenvía un mensaje sin reconstruirlo: bytes RFC822 originales con
        headers Resent-* agregados (RFC 5322). A diferencia de
        forward_message, conserva adjuntos, cuerpo HTML y headers
        originales intactos — pensado para archivar/auditar un correo tal
        cual, no para reenvío conversacional con comentario propio.
        """
        try:
            return _ok(_get_service().forward_raw(alias, folder_id, message_id, recipients))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(WRITE_SCOPE)
    def save_draft(
        alias: str,
        recipients: list[dict[str, Any]],
        subject: str = "",
        body_text: str = "",
        cc: list[dict[str, Any]] | None = None,
        bcc: list[dict[str, Any]] | None = None,
        body_html: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Guarda un mensaje nuevo en la carpeta de Borradores SIN ENVIARLO.

        Para preparar la respuesta a un mensaje existente, usar
        save_reply_draft. Devuelve la carpeta de borradores y el UID del
        borrador.

        `recipients`/`cc`/`bcc`: listas de {"email": str, "name": str|null}.
        `attachments`: listas de {"filename": str, "data": bytes|str, "content_type": str|null}.
        """
        try:
            return _ok(_get_service().save_draft(
                alias,
                recipients=recipients,
                subject=subject,
                body_text=body_text or None,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
                attachments=attachments,
            ))
        except MailCoreError as exc:
            return _err(exc)

    # ------------------------------------------------------------------
    # Adjuntos
    # ------------------------------------------------------------------

    @mcp.tool
    @scoped(READ_SCOPE)
    def list_attachments(alias: str, folder_id: str, message_id: str) -> dict[str, Any]:
        """Lista los adjuntos de un mensaje."""
        try:
            return _ok(_get_service().list_attachments(alias, folder_id, message_id))
        except MailCoreError as exc:
            return _err(exc)

    @mcp.tool
    @scoped(READ_SCOPE)
    def download_attachment(alias: str, folder_id: str, message_id: str, attachment_id: str) -> dict[str, Any]:
        """Descarga un adjunto. Devuelve su contenido en base64."""
        try:
            result = _get_service().download_attachment(alias, folder_id, message_id, attachment_id)
            if result.get("data") is not None:
                result["data"] = base64.b64encode(result["data"]).decode("ascii")
            return _ok(result)
        except MailCoreError as exc:
            return _err(exc)
