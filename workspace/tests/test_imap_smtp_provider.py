"""Tests de ImapSmtpProvider contra un IMAP falso en memoria.

``imaplib.IMAP4`` real requiere una conexión de red a un servidor de correo,
así que estos tests reemplazan ``_connect_imap`` por ``FakeIMAP4``: un doble
que guarda carpetas y mensajes en un dict y responde a los comandos IMAP que
``ImapSmtpProvider`` efectivamente emite (UID FETCH/SEARCH/STORE/COPY,
SELECT/LIST/CREATE/RENAME/DELETE), con la misma forma de respuesta
``(result, data)`` que devuelve imaplib real. Esta es la capa que
``test_rest_api.py`` no ejercita — ahí ``MailService`` está mockeado, así que
nunca llega a correr el parsing MIME ni los comandos IMAP reales.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from mail_core.config.config import AccountConfig
from mail_core.errors import FolderNotFoundError, MessageNotFoundError
from mail_core.providers import imap_smtp


def _decode(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _build_raw_message(
    subject: str,
    body: str = "cuerpo de prueba",
    attachments: list[tuple[str, bytes, str]] = (),
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "remitente@example.com"
    msg["To"] = "destino@example.com"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 19 Aug 2026 10:00:00 -0300"
    msg.set_content(body)
    for filename, data, content_type in attachments:
        maintype, subtype = content_type.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


class FakeIMAP4:
    """Doble mínimo de ``imaplib.IMAP4`` — solo lo que el provider usa."""

    def __init__(self, folders: dict[str, dict[int, bytes]]):
        self.folders = folders
        self.selected: str | None = None
        self._pending_delete: set[int] = set()

    def logout(self):
        return "BYE", [b"logout"]

    def select(self, mailbox):
        name = _decode(mailbox)
        if name not in self.folders:
            return "NO", [b"no such mailbox"]
        self.selected = name
        self._pending_delete = set()
        return "OK", [str(len(self.folders[name])).encode()]

    def list(self):
        lines = [f'(\\HasNoChildren) "/" "{name}"'.encode() for name in self.folders]
        return "OK", lines

    def create(self, mailbox):
        self.folders.setdefault(_decode(mailbox), {})
        return "OK", [b"created"]

    def rename(self, old, new):
        self.folders[_decode(new)] = self.folders.pop(_decode(old), {})
        return "OK", [b"renamed"]

    def delete(self, mailbox):
        self.folders.pop(_decode(mailbox), None)
        return "OK", [b"deleted"]

    def expunge(self):
        mailbox = self.folders[self.selected]
        for uid in self._pending_delete:
            mailbox.pop(uid, None)
        self._pending_delete = set()
        return "OK", [b""]

    def uid(self, command, *args):
        command = command.upper()
        if command == "FETCH":
            return self._fetch(*args)
        if command == "SEARCH":
            return self._search(*args)
        if command == "STORE":
            return self._store(*args)
        if command == "COPY":
            return self._copy(*args)
        raise NotImplementedError(command)

    def _fetch(self, uid_spec, _query):
        mailbox = self.folders[self.selected]
        uids = [int(u) for u in _decode(uid_spec).split(",")]
        chunks = [
            (f"{uid} (UID {uid} RFC822".encode(), mailbox[uid])
            for uid in uids
            if uid in mailbox
        ]
        chunks = list(chunks)
        if not chunks:
            return "NO", [None]
        return "OK", chunks

    def _search(self, _charset, *_criteria):
        # El provider solo reenvía el criterio de búsqueda al servidor real;
        # acá no hay servidor, así que devolvemos todos los UIDs de la
        # carpeta seleccionada y dejamos el filtrado fuera de este doble.
        uids = sorted(self.folders[self.selected])
        return "OK", [" ".join(str(u) for u in uids).encode() if uids else b""]

    def _store(self, uid_spec, flags_cmd, flags):
        uid = int(_decode(uid_spec))
        if flags_cmd == "+FLAGS" and "\\Deleted" in _decode(flags):
            self._pending_delete.add(uid)
        return "OK", [b""]

    def _copy(self, uid_spec, dest):
        uid = int(_decode(uid_spec))
        mailbox = self.folders[self.selected]
        if uid not in mailbox:
            return "NO", [b"not found"]
        self.folders.setdefault(_decode(dest), {})[uid] = mailbox[uid]
        return "OK", [b"copied"]


@pytest.fixture
def fake_imap(monkeypatch):
    fake = FakeIMAP4({"INBOX": {}, "Procesados": {}})
    monkeypatch.setattr(imap_smtp, "_connect_imap", lambda config: fake)
    return fake


@pytest.fixture
def provider(fake_imap):
    config = AccountConfig(
        alias="test",
        name="Test",
        provider="imap_smtp",
        email="test@example.com",
        options={"username": "test@example.com", "password": "x"},
    )
    return imap_smtp.ImapSmtpProvider(config)


def test_get_message_parsea_asunto_remitente_cuerpo_y_adjuntos(provider, fake_imap):
    fake_imap.folders["INBOX"][1] = _build_raw_message(
        "Hola", "cuerpo", attachments=[("doc.pdf", b"PDF-BYTES", "application/pdf")]
    )

    message = provider.get_message("INBOX", "1")

    assert message.subject == "Hola"
    assert message.sender.email == "remitente@example.com"
    assert message.body_text.strip() == "cuerpo"
    assert message.has_attachments is True
    assert [a.filename for a in message.attachments] == ["doc.pdf"]


def test_get_message_carpeta_inexistente_lanza_folder_not_found(provider):
    with pytest.raises(FolderNotFoundError):
        provider.get_message("NoExiste", "1")


def test_list_attachments_no_trae_los_bytes(provider, fake_imap):
    fake_imap.folders["INBOX"][1] = _build_raw_message(
        "Con adjunto", attachments=[("doc.pdf", b"PDF-BYTES", "application/pdf")]
    )

    attachments = provider.list_attachments("INBOX", "1")

    assert len(attachments) == 1
    assert attachments[0].filename == "doc.pdf"
    assert attachments[0].data is None


def test_download_attachment_trae_el_correcto_entre_varios(provider, fake_imap):
    """Regresión del bug real: con dos adjuntos, pedir el segundo debía
    traer el segundo — antes se rompía con NameError (comparaba contra una
    variable ``attachment_id`` que no existía en ese scope) y la API
    devolvía 500 sin detalle."""
    fake_imap.folders["INBOX"][1] = _build_raw_message(
        "Dos adjuntos",
        attachments=[
            ("a.pdf", b"CONTENIDO-A", "application/pdf"),
            ("b.txt", b"CONTENIDO-B", "text/plain"),
        ],
    )
    listado = provider.list_attachments("INBOX", "1")
    objetivo = next(a for a in listado if a.filename == "b.txt")

    resultado = provider.download_attachment("INBOX", "1", objetivo.attachment_id)

    assert resultado.filename == "b.txt"
    assert resultado.data == b"CONTENIDO-B"
    assert resultado.content_type == "text/plain"
    assert resultado.size == len(b"CONTENIDO-B")


def test_download_attachment_inexistente_lanza_message_not_found(provider, fake_imap):
    fake_imap.folders["INBOX"][1] = _build_raw_message("Sin adjuntos")

    with pytest.raises(MessageNotFoundError):
        provider.download_attachment("INBOX", "1", "id-que-no-existe")


def test_list_messages_ordena_del_mas_nuevo_al_mas_viejo(provider, fake_imap):
    fake_imap.folders["INBOX"][1] = _build_raw_message("Primero")
    fake_imap.folders["INBOX"][2] = _build_raw_message("Segundo")
    fake_imap.folders["INBOX"][3] = _build_raw_message("Tercero")

    messages = provider.list_messages("INBOX", limit=50, offset=0)

    assert [m.subject for m in messages] == ["Tercero", "Segundo", "Primero"]


def test_move_message_pasa_el_mensaje_a_la_carpeta_destino(provider, fake_imap):
    fake_imap.folders["INBOX"][1] = _build_raw_message("Para mover")

    provider.move_message("INBOX", "1", "Procesados")

    assert 1 not in fake_imap.folders["INBOX"]
    assert 1 in fake_imap.folders["Procesados"]
