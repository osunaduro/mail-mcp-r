"""API pública de la biblioteca: ``MailService``.

Este módulo define el contrato estable entre la biblioteca y todas las
aplicaciones consumidoras. Delega cada operación en el proveedor adecuado
según la cuenta seleccionada por su alias.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mail_core.config.config import MailConfig
from mail_core.domain import (
    Account,
    Attachment,
    Draft,
    Folder,
    Message,
    Recipient,
)
from mail_core.errors import AccountNotFoundError
from mail_core.providers.registry import create_provider


class MailService:
    """Punto único de acceso a las operaciones del dominio del correo.

    Se inicializa cargando el archivo de configuración (responsabilidad
    exclusiva de la biblioteca). El alias identifica la cuenta en toda
    operación; nunca se utilizan datos técnicos del proveedor.
    """

    def __init__(self, config_path: str | Path) -> None:
        self._config = MailConfig.load(config_path)
        self._providers: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Resolución de cuentas
    # ------------------------------------------------------------------

    def _provider_for(self, alias: str):
        if alias not in self._config.accounts:
            raise AccountNotFoundError(f"No existe la cuenta '{alias}'.")
        if alias not in self._providers:
            self._providers[alias] = create_provider(self._config.accounts[alias])
        return self._providers[alias]

    # ------------------------------------------------------------------
    # Gestión de cuentas
    # ------------------------------------------------------------------

    def list_accounts(self) -> list[Account]:
        """Devuelve las cuentas disponibles (sin información sensible)."""
        return [
            Account(
                alias=account.alias,
                name=account.name,
                email_address=account.email,
            )
            for account in self._config.accounts.values()
        ]

    def get_account(self, alias: str) -> dict[str, Any]:
        """Consulta la información pública de una cuenta."""
        account_cfg = self._config.accounts.get(alias)
        if account_cfg is None:
            raise AccountNotFoundError(f"No existe la cuenta '{alias}'.")
        account = Account(
            alias=alias,
            name=account_cfg.name,
            email_address=account_cfg.email,
        )
        return account.to_dict()

    # ------------------------------------------------------------------
    # Gestión de carpetas
    # ------------------------------------------------------------------

    def list_folders(self, alias: str) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self._provider_for(alias).list_folders()]

    def create_folder(self, alias: str, name: str) -> dict[str, Any]:
        return self._provider_for(alias).create_folder(name).to_dict()

    def rename_folder(
        self, alias: str, folder_id: str, new_name: str
    ) -> dict[str, Any]:
        return self._provider_for(alias).rename_folder(folder_id, new_name).to_dict()

    def delete_folder(self, alias: str, folder_id: str) -> None:
        self._provider_for(alias).delete_folder(folder_id)

    # ------------------------------------------------------------------
    # Gestión de mensajes
    # ------------------------------------------------------------------

    def list_messages(
        self, alias: str, folder_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        return [
            m.to_dict(include_body=False)
            for m in self._provider_for(alias).list_messages(folder_id, limit, offset)
        ]

    def get_message(self, alias: str, folder_id: str, message_id: str) -> dict[str, Any]:
        return self._provider_for(alias).get_message(folder_id, message_id).to_dict()

    def search_messages(
        self, alias: str, folder_id: str, query: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return [
            m.to_dict(include_body=False)
            for m in self._provider_for(alias).search_messages(folder_id, query, limit)
        ]

    def move_message(
        self, alias: str, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None:
        self._provider_for(alias).move_message(folder_id, message_id, dest_folder_id)

    def copy_message(
        self, alias: str, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None:
        self._provider_for(alias).copy_message(folder_id, message_id, dest_folder_id)

    def delete_message(self, alias: str, folder_id: str, message_id: str) -> None:
        self._provider_for(alias).delete_message(folder_id, message_id)

    def mark_read(
        self, alias: str, folder_id: str, message_id: str, read: bool = True
    ) -> None:
        self._provider_for(alias).mark_read(folder_id, message_id, read)

    def mark_flagged(
        self, alias: str, folder_id: str, message_id: str, flagged: bool = True
    ) -> None:
        self._provider_for(alias).mark_flagged(folder_id, message_id, flagged)

    # ------------------------------------------------------------------
    # Envío
    # ------------------------------------------------------------------

    def send(
        self,
        alias: str,
        *,
        to: list[dict[str, Any]],
        subject: str = "",
        body_text: str | None = None,
        body_html: str | None = None,
        cc: list[dict[str, Any]] | None = None,
        bcc: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        draft = _build_draft(to, cc, bcc, subject, body_text, body_html, attachments)
        self._provider_for(alias).send(draft)

    def reply(
        self,
        alias: str,
        folder_id: str,
        message_id: str,
        body_text: str,
        *,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> None:
        self._provider_for(alias).reply(
            folder_id, message_id, body_text, reply_all, include_original
        )

    def forward(
        self,
        alias: str,
        folder_id: str,
        message_id: str,
        recipients: list[str],
        body_text: str,
    ) -> None:
        rec_list = [Recipient(email=r) for r in recipients]
        self._provider_for(alias).forward(folder_id, message_id, rec_list, body_text)

    def save_draft(
        self,
        alias: str,
        *,
        recipients: list[dict[str, Any]],
        subject: str = "",
        body_text: str | None = None,
        body_html: str | None = None,
        cc: list[dict[str, Any]] | None = None,
        bcc: list[dict[str, Any]] | None = None,
    ) -> None:
        draft = _build_draft(recipients, cc, bcc, subject, body_text, body_html)
        self._provider_for(alias).save_draft(draft)

    # ------------------------------------------------------------------
    # Adjuntos
    # ------------------------------------------------------------------

    def list_attachments(
        self, alias: str, folder_id: str, message_id: str
    ) -> list[dict[str, Any]]:
        return [
            a.to_dict()
            for a in self._provider_for(alias).list_attachments(folder_id, message_id)
        ]

    def download_attachment(
        self, alias: str, folder_id: str, message_id: str, attachment_id: str
    ) -> dict[str, Any]:
        attachment = self._provider_for(alias).download_attachment(
            folder_id, message_id, attachment_id
        )
        data = attachment.to_dict()
        data["data"] = attachment.data if attachment.data is not None else None
        return data


def _as_recipient(value: dict[str, Any]) -> Recipient:
    return Recipient(email=value["email"], name=value.get("name"))


def _attachment_datum(value: dict[str, Any]) -> tuple[str, bytes, str | None]:
    filename = value["filename"]
    data = value.get("data") or b""
    if isinstance(data, str):
        data = data.encode("utf-8")
    content_type = value.get("content_type")
    return (filename, data, content_type)


def _build_draft(
    recipients: list[dict[str, Any]],
    cc: list[dict[str, Any]] | None,
    bcc: list[dict[str, Any]] | None,
    subject: str,
    body_text: str | None,
    body_html: str | None,
    attachments: list[dict[str, Any]] | None = None,
) -> Draft:
    return Draft(
        recipients=[_as_recipient(r) for r in recipients],
        cc=[_as_recipient(r) for r in cc or []],
        bcc=[_as_recipient(r) for r in bcc or []],
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        attachments=[_attachment_datum(a) for a in attachments or []],
    )