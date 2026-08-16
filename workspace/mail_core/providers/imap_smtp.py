"""Proveedor de correo basado en IMAP (recepción) y SMTP (envío).

Este módulo encapsula toda la complejidad del protocolo IMAP/SMTP.
Ningún otro componente conoce estos detalles.

Los identificadores de mensaje que se exponen son UIDs de IMAP, estables
mientras el mensaje exista en la carpeta.
"""

from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from email import message_from_bytes
from email.header import decode_header
from datetime import datetime
from hashlib import md5

from mail_core.config.config import AccountConfig
from mail_core.domain import Account, Attachment, Draft, Folder, Message, Recipient
from mail_core.errors import (
    AccountNotFoundError,
    AuthenticationError,
    ConnectionError,
    FolderNotFoundError,
    MessageNotFoundError,
    SendError,
)
from mail_core.providers.base import Provider
from mail_core.providers.registry import register

DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_PORT = 465
IMAP_TIMEOUT = 30

_UID_FETCH_RESPONSE_RE = re.compile(rb"UID (\d+)")


def _option_str(config: AccountConfig, key: str) -> str:
    value = config.options.get(key)
    if not isinstance(value, str) or not value:
        raise AccountNotFoundError(
            f"Configuración incompleta para la cuenta '{config.alias}'."
        )
    return value


def _option_int(config: AccountConfig, key: str, default: int) -> int:
    value = config.options.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _decode_mime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts: list[str] = []
        for text, charset in decode_header(value):
            if isinstance(text, bytes):
                parts.append(text.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(text)
        return "".join(parts)
    except Exception:
        return value


def _parse_addresses(value: str | None) -> list[Recipient]:
    if not value:
        return []
    recipients: list[Recipient] = []
    for name, addr in getaddresses([value]):
        if addr:
            recipients.append(Recipient(email=addr, name=_decode_mime(name) or None))
    return recipients


def _parse_date_header(value: str | None) -> datetime | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _connect_imap(config: AccountConfig) -> imaplib.IMAP4:
    host = _option_str(config, "imap_host")
    port = _option_int(config, "imap_port", DEFAULT_IMAP_PORT)
    username = _option_str(config, "username")
    password = _option_str(config, "password")

    try:
        if config.options.get("imap_ssl", True):
            context = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=IMAP_TIMEOUT)
        else:
            imap = imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ConnectionError("No se pudo conectar con el servidor de correo.") from exc

    try:
        imap.login(username, password)
    except imaplib.IMAP4.error as exc:
        try:
            imap.logout()
        except Exception:
            pass
        raise AuthenticationError("Autenticación fallida contra el servidor de correo.") from exc
    return imap


def _b(value: str) -> bytes:
    return value.encode("utf-8")


def _s(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _apply_resent_headers(raw: bytes, from_addr: str, to_addrs: list[str]) -> EmailMessage:
    """Parse a raw RFC822 message and prepend ``Resent-*`` headers.

    Pure function, no I/O: the rest of the message (subject, body,
    attachments, original headers) is left byte-for-byte as parsed —
    this is what makes a "raw" forward different from ``forward()``,
    which reconstructs a new message and loses everything but the text
    body. See RFC 5322 §3.6.6: ``Resent-*`` headers are the standard way
    to say "this message was resent unchanged".
    """
    msg = message_from_bytes(raw, policy=policy.default)
    msg["Resent-From"] = from_addr
    msg["Resent-To"] = ", ".join(to_addrs)
    msg["Resent-Date"] = formatdate(localtime=True)
    msg["Resent-Message-ID"] = make_msgid()
    return msg


@register("imap_smtp")
class ImapSmtpProvider(Provider):
    """Proveedor que combina IMAP para lectura y SMTP para envío."""

    def __init__(self, config: AccountConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    def _with_imap(self, operation):
        imap = _connect_imap(self._config)
        try:
            return operation(imap)
        except (FolderNotFoundError, MessageNotFoundError):
            raise
        except imaplib.IMAP4.error as exc:
            raise ConnectionError(
                "El servidor de correo rechazó la operación solicitada."
            ) from exc
        finally:
            try:
                imap.logout()
            except Exception:
                pass

    def _select(self, imap: imaplib.IMAP4, folder_id: str) -> None:
        result, _ = imap.select(_b(folder_id))
        if result != "OK":
            raise FolderNotFoundError("No existe la carpeta solicitada.")

    @staticmethod
    def _attachment_id(part) -> str:
        raw = part.get("Message-ID") or part.get_filename() or "attachment"
        return md5(_b(str(raw))).hexdigest()

    @classmethod
    def _parse_message(cls, raw: bytes, folder_id: str, uid: str) -> Message:
        msg = message_from_bytes(raw, policy=policy.default)

        attachments: list[Attachment] = []
        body_text: str | None = None
        body_html: str | None = None

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            disposition = part.get_content_disposition() or ""
            if filename is not None or disposition == "attachment":
                data = part.get_payload(decode=True) or b""
                attachments.append(
                    Attachment(
                        attachment_id=cls._attachment_id(part),
                        filename=_decode_mime(filename) or "attachment",
                        content_type=part.get_content_type(),
                        size=len(data),
                    )
                )
            elif part.get_content_type() == "text/plain" and body_text is None:
                body_text = _decode_mime(part.get_content())
            elif part.get_content_type() == "text/html" and body_html is None:
                body_html = _decode_mime(part.get_content())

        sender = _parse_addresses(msg.get("From"))
        return Message(
            message_id=uid,
            folder_id=folder_id,
            subject=_decode_mime(msg.get("Subject")) or "",
            sender=sender[0] if sender else None,
            recipients=_parse_addresses(msg.get("To")),
            cc=_parse_addresses(msg.get("Cc")),
            bcc=_parse_addresses(msg.get("Bcc")),
            body_text=body_text,
            body_html=body_html,
            date=_parse_date_header(msg.get("Date")),
            read="\\Seen" in msg.get("Flags", "") or False,
            has_attachments=bool(attachments),
            attachments=attachments,
        )

    @classmethod
    def _fetch_uid_bundle(
        cls, imap: imaplib.IMAP4, folder_id: str, uids: list[bytes]
    ) -> list[tuple[str, bytes]]:
        """Obtiene (UID, RFC822) para cada UID, en el orden dado."""
        if not uids:
            return []
        spec = ",".join(_s(u) for u in uids)
        result, data = imap.uid("FETCH", spec, "(UID RFC822)")
        if result != "OK":
            raise ConnectionError("No se pudieron leer los mensajes.")
        parsed: dict[str, bytes] = {}
        for chunk in data:
            if not isinstance(chunk, tuple):
                continue
            response = chunk[0]
            raw = chunk[1]
            match = _UID_FETCH_RESPONSE_RE.search(response if isinstance(response, bytes) else _b(response))
            if not match:
                continue
            parsed[match.group(1).decode("ascii")] = raw
        ordered_uids = [_s(u) for u in uids]
        return [(uid, parsed[uid]) for uid in ordered_uids if uid in parsed]

    def _read_message(self, imap: imaplib.IMAP4, folder_id: str, uid: str) -> Message:
        self._select(imap, folder_id)
        result, data = imap.uid("FETCH", _b(uid), "(UID RFC822)")
        if result != "OK" or not data or not isinstance(data[0], tuple):
            raise MessageNotFoundError("No se encontró el mensaje solicitado.")
        raw = data[0][1]
        return self._parse_message(raw, folder_id, uid)

    # ------------------------------------------------------------------
    # Carpetas
    # ------------------------------------------------------------------

    def list_folders(self) -> list[Folder]:
        def _run(imap: imaplib.IMAP4) -> list[Folder]:
            result, data = imap.list()
            if result != "OK":
                raise ConnectionError("No se pudieron listar las carpetas.")
            folders: list[Folder] = []
            for line in data:
                text = _s(line)
                parts = text.split(" ")
                if len(parts) < 3:
                    continue
                name = parts[2].strip('"')
                if name:
                    folders.append(Folder(folder_id=name, name=name))
            return folders

        return self._with_imap(_run)

    def create_folder(self, name: str) -> Folder:
        def _run(imap: imaplib.IMAP4) -> Folder:
            result, _ = imap.create(_b(name))
            if result != "OK":
                raise ConnectionError("No se pudo crear la carpeta.")
            return Folder(folder_id=name, name=name)

        return self._with_imap(_run)

    def rename_folder(self, folder_id: str, new_name: str) -> Folder:
        def _run(imap: imaplib.IMAP4) -> Folder:
            result, _ = imap.rename(_b(folder_id), _b(new_name))
            if result != "OK":
                raise FolderNotFoundError("No se pudo renombrar la carpeta.")
            return Folder(folder_id=new_name, name=new_name)

        return self._with_imap(_run)

    def delete_folder(self, folder_id: str) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            result, _ = imap.delete(_b(folder_id))
            if result != "OK":
                raise FolderNotFoundError("No se pudo eliminar la carpeta.")

        return self._with_imap(_run)

    # ------------------------------------------------------------------
    # Mensajes
    # ------------------------------------------------------------------

    def list_messages(
        self, folder_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        def _run(imap: imaplib.IMAP4) -> list[Message]:
            self._select(imap, folder_id)
            result, data = imap.uid("SEARCH", None, "ALL")
            if result != "OK" or not data or not data[0]:
                return []
            uids = data[0].split()
            selected = uids[max(0, len(uids) - offset - limit) : len(uids) - offset]
            selected = list(reversed(selected))
            fetched = self._fetch_uid_bundle(imap, folder_id, selected)
            messages = [self._parse_message(raw, folder_id, uid) for uid, raw in fetched]
            return messages

        return self._with_imap(_run)

    def get_message(self, folder_id: str, message_id: str) -> Message:
        def _run(imap: imaplib.IMAP4) -> Message:
            return self._read_message(imap, folder_id, message_id)

        return self._with_imap(_run)

    def search_messages(
        self, folder_id: str, query: str, limit: int = 50
    ) -> list[Message]:
        def _run(imap: imaplib.IMAP4) -> list[Message]:
            self._select(imap, folder_id)
            if query.strip():
                result, data = imap.uid("SEARCH", None, "SUBJECT", _b(query))
            else:
                result, data = imap.uid("SEARCH", None, "ALL")
            if result != "OK" or not data or not data[0]:
                return []
            uids = data[0].split()[:limit]
            fetched = self._fetch_uid_bundle(imap, folder_id, uids)
            return [self._parse_message(raw, folder_id, uid) for uid, raw in fetched]

        return self._with_imap(_run)

    def move_message(
        self, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            self._select(imap, folder_id)
            result, _ = imap.uid("COPY", _b(message_id), _b(dest_folder_id))
            if result != "OK":
                raise FolderNotFoundError("No se pudo mover el mensaje a la carpeta destino.")
            imap.uid("STORE", _b(message_id), "+FLAGS", "\\Deleted")
            imap.expunge()

        return self._with_imap(_run)

    def copy_message(
        self, folder_id: str, message_id: str, dest_folder_id: str
    ) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            self._select(imap, folder_id)
            result, _ = imap.uid("COPY", _b(message_id), _b(dest_folder_id))
            if result != "OK":
                raise FolderNotFoundError("No se pudo copiar el mensaje a la carpeta destino.")

        return self._with_imap(_run)

    def delete_message(self, folder_id: str, message_id: str) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            self._select(imap, folder_id)
            imap.uid("STORE", _b(message_id), "+FLAGS", "\\Deleted")
            imap.expunge()

        return self._with_imap(_run)

    def mark_read(self, folder_id: str, message_id: str, read: bool) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            self._select(imap, folder_id)
            flags = "+FLAGS" if read else "-FLAGS"
            imap.uid("STORE", _b(message_id), flags, "\\Seen")

        return self._with_imap(_run)

    def mark_flagged(self, folder_id: str, message_id: str, flagged: bool) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            self._select(imap, folder_id)
            flags = "+FLAGS" if flagged else "-FLAGS"
            imap.uid("STORE", _b(message_id), flags, "\\Flagged")

        return self._with_imap(_run)

    # ------------------------------------------------------------------
    # Envío
    # ------------------------------------------------------------------

    def _build_email(self, draft: Draft) -> EmailMessage:
        msg = EmailMessage()
        username = _option_str(self._config, "username")
        sender = draft.sender or Recipient(email=username)
        msg["From"] = formataddr((sender.name, sender.email)) if sender.name else sender.email
        if draft.recipients:
            msg["To"] = ", ".join(
                formataddr((r.name, r.email)) if r.name else r.email for r in draft.recipients
            )
        if draft.cc:
            msg["Cc"] = ", ".join(
                formataddr((r.name, r.email)) if r.name else r.email for r in draft.cc
            )
        if draft.bcc:
            msg["Bcc"] = ", ".join(
                formataddr((r.name, r.email)) if r.name else r.email for r in draft.bcc
            )
        msg["Subject"] = draft.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()

        if draft.body_text:
            msg.set_content(draft.body_text)
        if draft.body_html:
            if draft.body_text:
                msg.add_alternative(draft.body_html, subtype="html")
            else:
                msg.set_content(draft.body_html, subtype="html")
        if not draft.body_text and not draft.body_html:
            msg.set_content("")

        for filename, data, content_type in draft.attachments:
            maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

        return msg

    def _send(self, msg: EmailMessage, *, to_addrs: list[str] | None = None) -> None:
        host = _option_str(self._config, "smtp_host")
        port = _option_int(self._config, "smtp_port", DEFAULT_SMTP_PORT)
        username = _option_str(self._config, "username")
        password = _option_str(self._config, "password")

        try:
            if self._config.options.get("smtp_ssl", True):
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, timeout=IMAP_TIMEOUT, context=context) as smtp:
                    smtp.login(username, password)
                    smtp.send_message(msg, from_addr=username if to_addrs else None, to_addrs=to_addrs)
            else:
                with smtplib.SMTP(host, port, timeout=IMAP_TIMEOUT) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.login(username, password)
                    smtp.send_message(msg, from_addr=username if to_addrs else None, to_addrs=to_addrs)
        except smtplib.SMTPAuthenticationError as exc:
            raise AuthenticationError("Autenticación fallida contra el servidor de envío.") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise SendError("No se pudo enviar el mensaje.") from exc

    def send(self, draft: Draft) -> None:
        self._send(self._build_email(draft))

    def reply(
        self,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> None:
        original = self.get_message(folder_id, message_id)
        if original.sender is None:
            raise SendError("El mensaje original no tiene remitente.")

        recipients = [original.sender]
        cc: list[Recipient] = []
        if reply_all:
            recipients.extend(r for r in original.recipients if r != original.sender)
            cc = list(original.cc)

        msg = EmailMessage()
        msg["From"] = _option_str(self._config, "username")
        msg["To"] = ", ".join(r.email for r in recipients)
        if cc:
            msg["Cc"] = ", ".join(r.email for r in cc)
        msg["Subject"] = f"Re: {original.subject}"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if original.message_id:
            msg["References"] = original.message_id
            msg["In-Reply-To"] = original.message_id
        text = body_text
        if include_original and original.body_text:
            text += f"\n\nOn {original.date}, {original.sender.email} wrote:\n{original.body_text}"
        msg.set_content(text)
        self._send(msg)

    def forward(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
        body_text: str,
    ) -> None:
        original = self.get_message(folder_id, message_id)

        msg = EmailMessage()
        msg["From"] = _option_str(self._config, "username")
        msg["To"] = ", ".join(r.email for r in recipients)
        msg["Subject"] = f"Fwd: {original.subject}"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if original.message_id:
            msg["References"] = original.message_id
        text = body_text
        if original.body_text:
            text += f"\n\n---------- Mensaje original ----------\n{original.body_text}"
        msg.set_content(text)
        self._send(msg)

    def forward_raw(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
    ) -> None:
        """Reenvía el mensaje sin reconstruirlo: bytes RFC822 originales +
        headers ``Resent-*`` (ver ``_apply_resent_headers``). A diferencia de
        ``forward``, conserva adjuntos, cuerpo HTML y headers originales —
        pensado para archivo de auditoría, no para reenvío conversacional.
        """
        def _fetch_raw(imap: imaplib.IMAP4) -> bytes:
            self._select(imap, folder_id)
            result, data = imap.uid("FETCH", _b(message_id), "(RFC822)")
            if result != "OK" or not data or not isinstance(data[0], tuple):
                raise MessageNotFoundError("No se encontró el mensaje solicitado.")
            return data[0][1]

        raw = self._with_imap(_fetch_raw)
        username = _option_str(self._config, "username")
        to_addrs = [r.email for r in recipients]
        msg = _apply_resent_headers(raw, username, to_addrs)
        self._send(msg, to_addrs=to_addrs)

    def save_draft(self, draft: Draft) -> None:
        self._send(self._build_email(draft))

    # ------------------------------------------------------------------
    # Adjuntos
    # ------------------------------------------------------------------

    def list_attachments(self, folder_id: str, message_id: str) -> list[Attachment]:
        message = self.get_message(folder_id, message_id)
        return list(message.attachments)

    def download_attachment(
        self, folder_id: str, message_id: str, attachment_id: str
    ) -> Attachment:
        message = self.get_message(folder_id, message_id)
        for attachment in message.attachments:
            if attachment.attachment_id == attachment_id:
                return self._download_attachment(folder_id, message_id, attachment)
        raise MessageNotFoundError("No se encontró el adjunto solicitado.")

    def _download_attachment(
        self, folder_id: str, message_id: str, attachment: Attachment
    ) -> Attachment:
        def _run(imap: imaplib.IMAP4) -> Attachment:
            self._select(imap, folder_id)
            result, data = imap.uid("FETCH", _b(message_id), "(RFC822)")
            if result != "OK" or not data or not isinstance(data[0], tuple):
                raise MessageNotFoundError("No se encontró el mensaje solicitado.")
            raw = data[0][1]
            msg = message_from_bytes(raw, policy=policy.default)
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if filename is None:
                    continue
                payload = part.get_payload(decode=True) or b""
                if self._attachment_id(part) == attachment_id:
                    return Attachment(
                        attachment_id=attachment_id,
                        filename=attachment.filename,
                        content_type=part.get_content_type(),
                        size=len(payload),
                        data=payload,
                    )
            raise MessageNotFoundError("No se encontró el adjunto solicitado.")

        return self._with_imap(_run)
