"""Interfaz de proveedor de correo.

La interfaz ``Provider`` es la frontera de encapsulamiento de la biblioteca.
Cada mecanismo de comunicación (IMAP/SMTP, Graph, etc.) implementa esta
interfaz. Los consumidores nunca conocen estas clases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mail_core.domain import (
    Account,
    Attachment,
    Draft,
    Folder,
    Message,
    Recipient,
)


class Provider(ABC):
    """Operaciones funcionales de alto nivel sobre una cuenta de correo."""

    @abstractmethod
    def list_folders(self) -> list[Folder]: ...

    @abstractmethod
    def create_folder(self, name: str) -> Folder: ...

    @abstractmethod
    def rename_folder(self, folder_id: str, new_name: str) -> Folder: ...

    @abstractmethod
    def delete_folder(self, folder_id: str) -> None: ...

    @abstractmethod
    def list_messages(
        self, folder_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]: ...

    @abstractmethod
    def get_message(self, folder_id: str, message_id: str) -> Message: ...

    @abstractmethod
    def search_messages(
        self, folder_id: str, query: str, limit: int = 50
    ) -> list[Message]: ...

    @abstractmethod
    def move_message(
        self, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None: ...

    @abstractmethod
    def copy_message(
        self, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None: ...

    @abstractmethod
    def delete_message(self, folder_id: str, message_id: str) -> None: ...

    @abstractmethod
    def mark_read(self, folder_id: str, message_id: str, read: bool) -> None: ...

    @abstractmethod
    def mark_flagged(self, folder_id: str, message_id: str, flagged: bool) -> None: ...

    @abstractmethod
    def send(self, draft: Draft) -> None: ...

    @abstractmethod
    def reply(
        self,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> None: ...

    @abstractmethod
    def forward(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
        body_text: str,
    ) -> None: ...

    @abstractmethod
    def forward_raw(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
    ) -> None: ...

    @abstractmethod
    def save_draft(self, draft: Draft) -> None: ...

    @abstractmethod
    def list_attachments(self, folder_id: str, message_id: str) -> list[Attachment]: ...

    @abstractmethod
    def download_attachment(
        self, folder_id: str, message_id: str, attachment_id: str
    ) -> Attachment: ...
