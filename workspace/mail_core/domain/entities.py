"""Entidades del dominio del correo electrónico.

Estas entidades constituyen el lenguaje común entre la biblioteca y todas las
aplicaciones consumidoras. Son independientes de cualquier proveedor o protocolo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Recipient:
    """Destinatario de un mensaje."""

    email: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"email": self.email, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipient":
        return cls(email=data["email"], name=data.get("name"))


@dataclass(frozen=True)
class Attachment:
    """Adjunto de un mensaje.

    ``attachment_id`` es el identificador estable del adjunto dentro de la
    biblioteca. ``data`` solo está poblado cuando el adjunto ha sido descargado.
    """

    attachment_id: str
    filename: str
    content_type: str | None = None
    size: int | None = None
    data: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }


@dataclass(frozen=True)
class Message:
    """Mensaje de correo representado en el dominio de la biblioteca."""

    message_id: str
    folder_id: str
    subject: str = ""
    sender: Recipient | None = None
    recipients: list[Recipient] = field(default_factory=list)
    cc: list[Recipient] = field(default_factory=list)
    bcc: list[Recipient] = field(default_factory=list)
    body_text: str | None = None
    body_html: str | None = None
    date: datetime | None = None
    read: bool = False
    flagged: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    has_attachments: bool = False

    def to_dict(self, include_body: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "message_id": self.message_id,
            "folder_id": self.folder_id,
            "subject": self.subject,
            "sender": self.sender.to_dict() if self.sender else None,
            "recipients": [r.to_dict() for r in self.recipients],
            "cc": [r.to_dict() for r in self.cc],
            "bcc": [r.to_dict() for r in self.bcc],
            "date": self.date.isoformat() if self.date else None,
            "read": self.read,
            "flagged": self.flagged,
            "has_attachments": self.has_attachments,
            "attachments": [a.to_dict() for a in self.attachments],
        }
        if include_body:
            data["body_text"] = self.body_text
            data["body_html"] = self.body_html
        return data


@dataclass(frozen=True)
class Folder:
    """Carpeta o buzón de una cuenta."""

    folder_id: str
    name: str
    path: str | None = None
    delimiter: str | None = None
    message_count: int | None = None
    unread_count: int | None = None
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder_id": self.folder_id,
            "name": self.name,
            "path": self.path,
            "delimiter": self.delimiter,
            "message_count": self.message_count,
            "unread_count": self.unread_count,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True)
class Account:
    """Cuenta de correo configurada, tal como la ve un consumidor.

    Solo se expone información no sensible: alias, nombre descriptivo y estado.
    """

    alias: str
    name: str
    email_address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "name": self.name,
            "email_address": self.email_address,
        }


@dataclass(frozen=True)
class Draft:
    """Borrador a enviar, entidad de entrada para las operaciones de envío."""

    sender: Recipient | None = None
    recipients: list[Recipient] = field(default_factory=list)
    cc: list[Recipient] = field(default_factory=list)
    bcc: list[Recipient] = field(default_factory=list)
    subject: str = ""
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[tuple[str, bytes, str | None]] = field(default_factory=list)
