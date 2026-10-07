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
import time
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from email import message_from_bytes
from email.header import decode_header
from datetime import datetime
from hashlib import md5

from mail_core.config.config import AccountConfig
from mail_core.domain import (
    Account,
    Attachment,
    Draft,
    Folder,
    Message,
    Recipient,
    SavedDraft,
    SendResult,
)
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
_LIST_LINE_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>(?:[^"\\]|\\.)*)"|NIL)\s+(?P<name>.+)$')
_APPENDUID_RE = re.compile(rb"APPENDUID \d+ (\d+)")

# Carpetas especiales: atributo SPECIAL-USE (RFC 6154) y, si el servidor no
# lo anuncia, nombres habituales. ``drafts_folder``/``sent_folder`` en las
# opciones de la cuenta tienen prioridad sobre ambos.
_SPECIAL_USE_FLAGS = {"drafts": "\\drafts", "sent": "\\sent"}
_SPECIAL_FALLBACK_NAMES = {
    "drafts": [
        "Drafts", "INBOX.Drafts", "INBOX/Drafts", "Borradores", "INBOX.Borradores",
        "INBOX/Borradores", "Draft", "[Gmail]/Drafts", "[Gmail]/Borradores",
    ],
    "sent": [
        "Sent", "INBOX.Sent", "INBOX/Sent", "Sent Items", "Sent Messages", "Sent Mail",
        "Enviados", "INBOX.Enviados", "INBOX/Enviados", "Elementos enviados",
        "[Gmail]/Sent Mail", "[Gmail]/Enviados",
    ],
}
_SPECIAL_OPTION = {"drafts": "drafts_folder", "sent": "sent_folder"}
_SPECIAL_DEFAULT_NAME = {"drafts": "Drafts", "sent": "Sent"}

# Servidores SMTP que ya guardan solos una copia en Enviados: guardarla de
# nuevo por IMAP la duplicaría. ``save_sent`` en las opciones lo fuerza.
_AUTO_SENT_SMTP_HOSTS = ("gmail.com", "googlemail.com", "office365.com", "outlook.com")


def _unquote_mailbox(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return name


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


def _mb(name: str) -> bytes:
    """Nombre de carpeta listo para un comando IMAP.

    ``imaplib`` no entrecomilla los argumentos: un nombre con espacios
    ("Sent Items", "Elementos enviados") rompería el comando.
    """
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        return _b(name)
    if re.search(r'[\s"\\(){}%*\]]', name) or not name:
        return _b('"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return _b(name)


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
        result, _ = imap.select(_mb(folder_id))
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
            internet_message_id=(msg.get("Message-ID") or "").strip() or None,
            references=(msg.get("References") or "").strip() or None,
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

    @staticmethod
    def _list_mailboxes(imap: imaplib.IMAP4) -> list[tuple[str, str]]:
        """Devuelve (flags, nombre) de cada carpeta, flags en minúsculas."""
        result, data = imap.list()
        if result != "OK":
            raise ConnectionError("No se pudieron listar las carpetas.")
        mailboxes: list[tuple[str, str]] = []
        for line in data:
            if line is None:
                continue
            text = _s(line).strip()
            match = _LIST_LINE_RE.match(text)
            if not match:
                continue
            name = _unquote_mailbox(match.group("name"))
            if name:
                mailboxes.append((match.group("flags").lower(), name))
        return mailboxes

    def list_folders(self) -> list[Folder]:
        def _run(imap: imaplib.IMAP4) -> list[Folder]:
            return [
                Folder(folder_id=name, name=name)
                for _, name in self._list_mailboxes(imap)
            ]

        return self._with_imap(_run)

    def _special_folder(self, imap: imaplib.IMAP4, kind: str) -> str:
        """Resuelve la carpeta de borradores (``drafts``) o enviados (``sent``).

        Orden: opción explícita de la cuenta, atributo SPECIAL-USE, nombres
        habituales. Si no existe ninguna, la crea con el nombre por defecto.
        """
        configured = self._config.options.get(_SPECIAL_OPTION[kind])
        if isinstance(configured, str) and configured:
            return configured

        mailboxes = self._list_mailboxes(imap)
        flag = _SPECIAL_USE_FLAGS[kind]
        for flags, name in mailboxes:
            if flag in flags.split():
                return name
        by_lower = {name.lower(): name for _, name in mailboxes}
        for candidate in _SPECIAL_FALLBACK_NAMES[kind]:
            if candidate.lower() in by_lower:
                return by_lower[candidate.lower()]

        name = _SPECIAL_DEFAULT_NAME[kind]
        result, _ = imap.create(_mb(name))
        if result != "OK":
            raise FolderNotFoundError(
                f"No se encontró la carpeta de {'borradores' if kind == 'drafts' else 'enviados'}."
            )
        return name

    @staticmethod
    def _append(
        imap: imaplib.IMAP4, folder_id: str, msg: EmailMessage, flags: str
    ) -> str | None:
        """Guarda ``msg`` en ``folder_id`` vía IMAP APPEND; devuelve el UID si
        el servidor lo informa (UIDPLUS)."""
        result, data = imap.append(
            _mb(folder_id), flags, imaplib.Time2Internaldate(time.time()), msg.as_bytes()
        )
        if result != "OK":
            raise ConnectionError("No se pudo guardar el mensaje en la carpeta.")
        for chunk in data or []:
            if isinstance(chunk, (bytes, str)):
                match = _APPENDUID_RE.search(chunk if isinstance(chunk, bytes) else _b(chunk))
                if match:
                    return match.group(1).decode("ascii")
        return None

    def create_folder(self, name: str) -> Folder:
        def _run(imap: imaplib.IMAP4) -> Folder:
            result, _ = imap.create(_mb(name))
            if result != "OK":
                raise ConnectionError("No se pudo crear la carpeta.")
            return Folder(folder_id=name, name=name)

        return self._with_imap(_run)

    def rename_folder(self, folder_id: str, new_name: str) -> Folder:
        def _run(imap: imaplib.IMAP4) -> Folder:
            result, _ = imap.rename(_mb(folder_id), _mb(new_name))
            if result != "OK":
                raise FolderNotFoundError("No se pudo renombrar la carpeta.")
            return Folder(folder_id=new_name, name=new_name)

        return self._with_imap(_run)

    def delete_folder(self, folder_id: str) -> None:
        def _run(imap: imaplib.IMAP4) -> None:
            result, _ = imap.delete(_mb(folder_id))
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
            result, _ = imap.uid("COPY", _b(message_id), _mb(dest_folder_id))
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
            result, _ = imap.uid("COPY", _b(message_id), _mb(dest_folder_id))
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

    def _should_save_sent(self) -> bool:
        configured = self._config.options.get("save_sent")
        if isinstance(configured, bool):
            return configured
        host = str(self._config.options.get("smtp_host") or "").lower()
        return not any(
            host == suffix or host.endswith("." + suffix) for suffix in _AUTO_SENT_SMTP_HOSTS
        )

    def _send_and_store(self, msg: EmailMessage, *, to_addrs: list[str] | None = None) -> SendResult:
        """Envía por SMTP y guarda una copia en Enviados.

        SMTP solo entrega el mensaje: la copia en Enviados la tiene que
        guardar el cliente (salvo servidores que lo hacen solos, ver
        ``_should_save_sent``). Si guardar la copia falla, el envío ya se
        hizo y no se informa como error, solo como ``warning``.
        """
        self._send(msg, to_addrs=to_addrs)
        if not self._should_save_sent():
            return SendResult(sent=True, saved_to_sent=False)

        def _run(imap: imaplib.IMAP4) -> SendResult:
            folder = self._special_folder(imap, "sent")
            uid = self._append(imap, folder, msg, "(\\Seen)")
            return SendResult(
                sent=True, saved_to_sent=True, sent_folder_id=folder, sent_message_id=uid
            )

        try:
            return self._with_imap(_run)
        except Exception:  # el envío ya salió: nunca reportarlo como fallido
            return SendResult(
                sent=True,
                saved_to_sent=False,
                warning="El mensaje se envió, pero no se pudo guardar la copia en Enviados.",
            )

    def _save_to_drafts(self, msg: EmailMessage) -> SavedDraft:
        def _run(imap: imaplib.IMAP4) -> SavedDraft:
            folder = self._special_folder(imap, "drafts")
            uid = self._append(imap, folder, msg, "(\\Draft \\Seen)")
            return SavedDraft(folder_id=folder, message_id=uid)

        return self._with_imap(_run)

    def send(self, draft: Draft) -> SendResult:
        return self._send_and_store(self._build_email(draft))

    def _build_reply(
        self,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool,
        include_original: bool,
    ) -> EmailMessage:
        original = self.get_message(folder_id, message_id)
        if original.sender is None:
            raise SendError("El mensaje original no tiene remitente.")

        own = {
            str(self._config.options.get("username") or "").lower(),
            str(self._config.email or "").lower(),
        }
        recipients = [original.sender]
        cc: list[Recipient] = []
        if reply_all:
            seen = {original.sender.email.lower()}
            for r in original.recipients:
                if r.email.lower() not in seen and r.email.lower() not in own:
                    recipients.append(r)
                    seen.add(r.email.lower())
            cc = [
                r for r in original.cc
                if r.email.lower() not in seen and r.email.lower() not in own
            ]

        msg = EmailMessage()
        msg["From"] = _option_str(self._config, "username")
        msg["To"] = ", ".join(r.email for r in recipients)
        if cc:
            msg["Cc"] = ", ".join(r.email for r in cc)
        subject = original.subject or ""
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if original.internet_message_id:
            msg["In-Reply-To"] = original.internet_message_id
            references = " ".join(
                part for part in (original.references, original.internet_message_id) if part
            )
            msg["References"] = references
        text = body_text
        if include_original and original.body_text:
            text += f"\n\nOn {original.date}, {original.sender.email} wrote:\n{original.body_text}"
        msg.set_content(text)
        return msg

    def reply(
        self,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> SendResult:
        msg = self._build_reply(folder_id, message_id, body_text, reply_all, include_original)
        return self._send_and_store(msg)

    def save_reply_draft(
        self,
        folder_id: str,
        message_id: str,
        body_text: str,
        reply_all: bool = False,
        include_original: bool = True,
    ) -> SavedDraft:
        msg = self._build_reply(folder_id, message_id, body_text, reply_all, include_original)
        return self._save_to_drafts(msg)

    def forward(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
        body_text: str,
    ) -> SendResult:
        original = self.get_message(folder_id, message_id)

        msg = EmailMessage()
        msg["From"] = _option_str(self._config, "username")
        msg["To"] = ", ".join(r.email for r in recipients)
        msg["Subject"] = f"Fwd: {original.subject}"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if original.internet_message_id:
            msg["References"] = original.internet_message_id
        text = body_text
        if original.body_text:
            text += f"\n\n---------- Mensaje original ----------\n{original.body_text}"
        msg.set_content(text)
        return self._send_and_store(msg)

    def forward_raw(
        self,
        folder_id: str,
        message_id: str,
        recipients: list[Recipient],
    ) -> SendResult:
        """Reenvía el mensaje sin reconstruirlo: bytes RFC822 originales +
        headers ``Resent-*`` (ver ``_apply_resent_headers``). A diferencia de
        ``forward``, conserva adjuntos, cuerpo HTML y headers originales —
        pensado para archivo de auditoría, no para reenvío conversacional.
        Por eso no guarda copia en Enviados.
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
        return SendResult(sent=True, saved_to_sent=False)

    def save_draft(self, draft: Draft) -> SavedDraft:
        """Guarda el borrador en la carpeta de borradores. NO lo envía."""
        return self._save_to_drafts(self._build_email(draft))

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
                if self._attachment_id(part) == attachment.attachment_id:
                    return Attachment(
                        attachment_id=attachment.attachment_id,
                        filename=attachment.filename,
                        content_type=part.get_content_type(),
                        size=len(payload),
                        data=payload,
                    )
            raise MessageNotFoundError("No se encontró el adjunto solicitado.")

        return self._with_imap(_run)
