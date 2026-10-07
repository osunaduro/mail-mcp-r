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

from email import message_from_bytes, policy
from email.message import EmailMessage

import pytest

from mail_core.config.config import AccountConfig
from mail_core.domain import Draft, Recipient
from mail_core.errors import FolderNotFoundError, MessageNotFoundError
from mail_core.providers import imap_smtp


def _decode(value: bytes | str) -> str:
    text = value.decode() if isinstance(value, bytes) else value
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


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

    def __init__(
        self,
        folders: dict[str, dict[int, bytes]],
        special_use: dict[str, str] | None = None,
    ):
        self.folders = folders
        self.special_use = special_use or {}
        self.selected: str | None = None
        self._pending_delete: set[int] = set()
        self.appended: list[tuple[str, str, bytes]] = []

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
        lines = [
            f'(\\HasNoChildren{" " + self.special_use[name] if name in self.special_use else ""})'
            f' "/" "{name}"'.encode()
            for name in self.folders
        ]
        return "OK", lines

    def append(self, mailbox, flags, _date_time, message):
        name = _decode(mailbox)
        if name not in self.folders:
            return "NO", [b"[TRYCREATE] no such mailbox"]
        box = self.folders[name]
        uid = max(box, default=0) + 1
        box[uid] = message
        self.appended.append((name, flags, message))
        return "OK", [f"[APPENDUID 1 {uid}] APPEND completed".encode()]

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


# ----------------------------------------------------------------------
# Borradores y copia en Enviados
# ----------------------------------------------------------------------


class FakeSMTP:
    """Registra lo que se habría enviado por SMTP."""

    def __init__(self, monkeypatch, provider):
        self.sent: list = []
        monkeypatch.setattr(
            provider, "_send", lambda msg, to_addrs=None: self.sent.append(msg)
        )


def _provider_with(fake_imap, **options):
    config = AccountConfig(
        alias="test",
        name="Test",
        provider="imap_smtp",
        email="test@example.com",
        options={"username": "test@example.com", "password": "x", **options},
    )
    return imap_smtp.ImapSmtpProvider(config)


def test_save_draft_no_envia_y_guarda_en_borradores(provider, fake_imap, monkeypatch):
    """Regresión: save_draft enviaba el correo por SMTP en vez de guardarlo."""
    fake_imap.folders["Borradores"] = {}
    fake_imap.special_use["Borradores"] = "\\Drafts"
    smtp = FakeSMTP(monkeypatch, provider)

    result = provider.save_draft(
        Draft(recipients=[Recipient(email="cliente@example.com")], subject="Presupuesto", body_text="Hola")
    )

    assert smtp.sent == []
    assert result.folder_id == "Borradores"
    assert result.message_id == "1"
    assert result.sent is False
    name, flags, raw = fake_imap.appended[0]
    assert name == "Borradores"
    assert "\\Draft" in flags
    assert b"Subject: Presupuesto" in raw


def test_save_draft_sin_special_use_usa_nombre_habitual(provider, fake_imap, monkeypatch):
    fake_imap.folders["INBOX.Drafts"] = {}
    FakeSMTP(monkeypatch, provider)

    result = provider.save_draft(Draft(recipients=[Recipient(email="a@example.com")]))

    assert result.folder_id == "INBOX.Drafts"


def test_save_draft_crea_la_carpeta_si_no_existe(provider, fake_imap, monkeypatch):
    FakeSMTP(monkeypatch, provider)

    result = provider.save_draft(Draft(recipients=[Recipient(email="a@example.com")]))

    assert result.folder_id == "Drafts"
    assert 1 in fake_imap.folders["Drafts"]


def test_save_reply_draft_no_envia_y_encadena_con_el_original(provider, fake_imap, monkeypatch):
    original = EmailMessage()
    original["From"] = "cliente@example.com"
    original["To"] = "test@example.com"
    original["Subject"] = "Consulta"
    original["Message-ID"] = "<orig-123@example.com>"
    original.set_content("¿Tienen precio?")
    fake_imap.folders["INBOX"][7] = original.as_bytes()
    fake_imap.folders["Drafts"] = {}
    smtp = FakeSMTP(monkeypatch, provider)

    result = provider.save_reply_draft("INBOX", "7", "Sí, te paso el precio.")

    assert smtp.sent == []
    assert result.folder_id == "Drafts"
    draft = message_from_bytes(fake_imap.folders["Drafts"][1], policy=policy.default)
    assert draft["To"] == "cliente@example.com"
    assert draft["Subject"] == "Re: Consulta"
    assert draft["In-Reply-To"] == "<orig-123@example.com>"
    assert "<orig-123@example.com>" in draft["References"]


def test_send_guarda_copia_en_enviados(provider, fake_imap, monkeypatch):
    """Regresión: el envío no dejaba ninguna copia en Enviados."""
    fake_imap.folders["Sent Items"] = {}
    smtp = FakeSMTP(monkeypatch, provider)

    result = provider.send(
        Draft(recipients=[Recipient(email="a@example.com")], subject="Hola", body_text="x")
    )

    assert len(smtp.sent) == 1
    assert result.sent is True
    assert result.saved_to_sent is True
    assert result.sent_folder_id == "Sent Items"
    name, flags, _ = fake_imap.appended[0]
    assert name == "Sent Items"
    assert "\\Seen" in flags


def test_reply_envia_y_guarda_copia_en_enviados(provider, fake_imap, monkeypatch):
    fake_imap.folders["INBOX"][1] = _build_raw_message("Consulta")
    fake_imap.folders["Enviados"] = {}
    smtp = FakeSMTP(monkeypatch, provider)

    result = provider.reply("INBOX", "1", "Respuesta")

    assert len(smtp.sent) == 1
    assert result.saved_to_sent is True
    assert result.sent_folder_id == "Enviados"


def test_gmail_no_duplica_la_copia_en_enviados(fake_imap, monkeypatch):
    provider = _provider_with(fake_imap, smtp_host="smtp.gmail.com")
    fake_imap.folders["[Gmail]/Sent Mail"] = {}
    FakeSMTP(monkeypatch, provider)

    result = provider.send(Draft(recipients=[Recipient(email="a@example.com")]))

    assert result.sent is True
    assert result.saved_to_sent is False
    assert fake_imap.appended == []


def test_save_sent_y_sent_folder_configurables(fake_imap, monkeypatch):
    provider = _provider_with(
        fake_imap, smtp_host="smtp.gmail.com", save_sent=True, sent_folder="Procesados"
    )
    FakeSMTP(monkeypatch, provider)

    result = provider.send(Draft(recipients=[Recipient(email="a@example.com")]))

    assert result.saved_to_sent is True
    assert result.sent_folder_id == "Procesados"


def test_fallo_al_guardar_copia_no_anula_el_envio(provider, fake_imap, monkeypatch):
    fake_imap.folders["Sent"] = {}
    monkeypatch.setattr(fake_imap, "append", lambda *a: ("NO", [b"quota exceeded"]))
    smtp = FakeSMTP(monkeypatch, provider)

    result = provider.send(Draft(recipients=[Recipient(email="a@example.com")]))

    assert len(smtp.sent) == 1
    assert result.sent is True
    assert result.saved_to_sent is False
    assert result.warning


def test_nombres_de_carpeta_con_espacios_se_entrecomillan():
    assert imap_smtp._mb("INBOX") == b"INBOX"
    assert imap_smtp._mb("Sent Items") == b'"Sent Items"'
    assert imap_smtp._mb('a"b') == b'"a\\"b"'
