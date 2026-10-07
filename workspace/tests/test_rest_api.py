"""Tests for mcp_server.rest_api using a fake MailService.

No real IMAP/SMTP server is reachable in CI, so `get_service()` is
monkeypatched to a fake that records calls and returns canned data — the
same level of mocking the plan calls for. Each route is checked for two
things: it calls the correct MailService method with the correct
arguments, and the app's Bearer-token/error-mapping plumbing works.

The routes list is imported directly from rest_api (not the module-level
`app`, whose middleware bakes in whatever MAIL_SERVICE_TOKEN happened to be
set in the environment at import time) so tests can pick a known token.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

import mcp_server.rest_api as rest_api
from mail_core.domain import Account
from mail_core.errors import (
    AccountNotFoundError,
    AttachmentNotFoundError,
    ConfigError,
    MessageNotFoundError,
    ProviderError,
)
from mcp_server.auth import BearerTokenMiddleware

TOKEN = "test-service-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeMailService:
    def __init__(self):
        self.calls = []
        self._raise = None

    def raise_next(self, exc):
        self._raise = exc

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self._raise is not None:
            exc, self._raise = self._raise, None
            raise exc

    # -- Cuentas ---------------------------------------------------------
    def list_accounts(self):
        self._record("list_accounts")
        return [Account(alias="work", name="Correo work", email_address="work@example.com")]

    def get_account(self, alias):
        self._record("get_account", alias)
        return {"alias": alias}

    # -- Carpetas ----------------------------------------------------------
    def list_folders(self, alias):
        self._record("list_folders", alias)
        return [{"id": "INBOX"}]

    def create_folder(self, alias, name):
        self._record("create_folder", alias, name)
        return {"id": name}

    def rename_folder(self, alias, folder_id, new_name):
        self._record("rename_folder", alias, folder_id, new_name)
        return {"id": folder_id, "name": new_name}

    def delete_folder(self, alias, folder_id):
        self._record("delete_folder", alias, folder_id)
        return None

    # -- Mensajes ----------------------------------------------------------
    def list_messages(self, alias, folder_id, limit, offset):
        self._record("list_messages", alias, folder_id, limit, offset)
        return [{"id": "1"}]

    def get_message(self, alias, folder_id, message_id):
        self._record("get_message", alias, folder_id, message_id)
        return {"id": message_id}

    def search_messages(self, alias, folder_id, query, limit):
        self._record("search_messages", alias, folder_id, query, limit)
        return [{"id": "1"}]

    def move_message(self, alias, folder_id, message_id, dest_folder_id):
        self._record("move_message", alias, folder_id, message_id, dest_folder_id)
        return None

    def copy_message(self, alias, folder_id, message_id, dest_folder_id):
        self._record("copy_message", alias, folder_id, message_id, dest_folder_id)
        return None

    def delete_message(self, alias, folder_id, message_id):
        self._record("delete_message", alias, folder_id, message_id)
        return None

    def mark_read(self, alias, folder_id, message_id, read):
        self._record("mark_read", alias, folder_id, message_id, read)
        return None

    def mark_flagged(self, alias, folder_id, message_id, flagged):
        self._record("mark_flagged", alias, folder_id, message_id, flagged)
        return None

    # -- Envío ---------------------------------------------------------
    def send(self, alias, **kwargs):
        self._record("send", alias, **kwargs)
        return None

    def reply(self, alias, folder_id, message_id, body_text, **kwargs):
        self._record("reply", alias, folder_id, message_id, body_text, **kwargs)
        return None

    def forward(self, alias, folder_id, message_id, recipients, body_text):
        self._record("forward", alias, folder_id, message_id, recipients, body_text)
        return None

    def forward_raw(self, alias, folder_id, message_id, recipients):
        self._record("forward_raw", alias, folder_id, message_id, recipients)
        return None

    def save_reply_draft(self, alias, folder_id, message_id, body_text, **kwargs):
        self._record("save_reply_draft", alias, folder_id, message_id, body_text, **kwargs)
        return {"folder_id": "Drafts", "message_id": "9", "sent": False}

    def save_draft(self, alias, **kwargs):
        self._record("save_draft", alias, **kwargs)
        return None

    # -- Adjuntos ---------------------------------------------------------
    def list_attachments(self, alias, folder_id, message_id):
        self._record("list_attachments", alias, folder_id, message_id)
        return [{"id": "a1"}]

    def download_attachment(self, alias, folder_id, message_id, attachment_id):
        self._record("download_attachment", alias, folder_id, message_id, attachment_id)
        return {"filename": "doc.pdf", "content_type": "application/pdf", "data": b"PDF-BYTES"}


def _make_app(token: str | None = TOKEN) -> Starlette:
    return Starlette(
        routes=rest_api.routes,
        middleware=[Middleware(BearerTokenMiddleware, token=token or "")],
    )


@pytest.fixture
def fake(monkeypatch):
    service = FakeMailService()
    monkeypatch.setattr(rest_api, "get_service", lambda: service)
    return service


@pytest.fixture
def client():
    with TestClient(_make_app()) as c:
        yield c


# ==========================================================================
# Auth
# ==========================================================================

def test_sin_authorization_header_da_401(client, fake):
    r = client.get("/accounts")
    assert r.status_code == 401


def test_token_incorrecto_da_401(client, fake):
    r = client.get("/accounts", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_sin_mail_service_token_configurado_da_503(fake):
    with TestClient(_make_app(token="")) as c:
        r = c.get("/accounts", headers=AUTH)
        assert r.status_code == 503


def test_token_correcto_pasa(client, fake):
    r = client.get("/accounts", headers=AUTH)
    assert r.status_code == 200


# ==========================================================================
# Cuentas
# ==========================================================================

def test_list_accounts(client, fake):
    r = client.get("/accounts", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == [
        {"alias": "work", "name": "Correo work", "email_address": "work@example.com"}
    ]
    assert fake.calls == [("list_accounts", (), {})]


def test_get_account(client, fake):
    r = client.get("/accounts/work", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"alias": "work"}
    assert fake.calls == [("get_account", ("work",), {})]


# ==========================================================================
# Carpetas
# ==========================================================================

def test_list_folders(client, fake):
    r = client.get("/accounts/work/folders", headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [("list_folders", ("work",), {})]


def test_create_folder(client, fake):
    r = client.post("/accounts/work/folders", headers=AUTH, json={"name": "Archive"})
    assert r.status_code == 200
    assert fake.calls == [("create_folder", ("work", "Archive"), {})]


def test_rename_folder(client, fake):
    r = client.patch(
        "/accounts/work/folders/INBOX", headers=AUTH, json={"new_name": "Bandeja"}
    )
    assert r.status_code == 200
    assert fake.calls == [("rename_folder", ("work", "INBOX", "Bandeja"), {})]


def test_delete_folder(client, fake):
    r = client.delete("/accounts/work/folders/Archive", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert fake.calls == [("delete_folder", ("work", "Archive"), {})]


# ==========================================================================
# Mensajes
# ==========================================================================

def test_list_messages_con_query_params(client, fake):
    r = client.get(
        "/accounts/work/folders/INBOX/messages?limit=10&offset=5", headers=AUTH
    )
    assert r.status_code == 200
    assert fake.calls == [("list_messages", ("work", "INBOX", 10, 5), {})]


def test_list_messages_defaults(client, fake):
    r = client.get("/accounts/work/folders/INBOX/messages", headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [("list_messages", ("work", "INBOX", 50, 0), {})]


def test_get_message(client, fake):
    r = client.get("/accounts/work/folders/INBOX/messages/42", headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [("get_message", ("work", "INBOX", "42"), {})]


def test_search_messages(client, fake):
    r = client.get(
        "/accounts/work/folders/INBOX/messages/search?q=hola&limit=5", headers=AUTH
    )
    assert r.status_code == 200
    assert fake.calls == [("search_messages", ("work", "INBOX", "hola", 5), {})]


def test_move_message(client, fake):
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/move",
        headers=AUTH,
        json={"dest_folder_id": "Archive"},
    )
    assert r.status_code == 200
    assert fake.calls == [("move_message", ("work", "INBOX", "42", "Archive"), {})]


def test_copy_message(client, fake):
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/copy",
        headers=AUTH,
        json={"dest_folder_id": "Archive"},
    )
    assert r.status_code == 200
    assert fake.calls == [("copy_message", ("work", "INBOX", "42", "Archive"), {})]


def test_delete_message(client, fake):
    r = client.delete("/accounts/work/folders/INBOX/messages/42", headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [("delete_message", ("work", "INBOX", "42"), {})]


def test_mark_read_default_true(client, fake):
    r = client.post("/accounts/work/folders/INBOX/messages/42/read", headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [("mark_read", ("work", "INBOX", "42", True), {})]


def test_mark_read_explicit_false(client, fake):
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/read", headers=AUTH, json={"read": False}
    )
    assert r.status_code == 200
    assert fake.calls == [("mark_read", ("work", "INBOX", "42", False), {})]


def test_mark_flagged(client, fake):
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/flag", headers=AUTH, json={"flagged": True}
    )
    assert r.status_code == 200
    assert fake.calls == [("mark_flagged", ("work", "INBOX", "42", True), {})]


# ==========================================================================
# Envío
# ==========================================================================

def test_send_message(client, fake):
    body = {"to": [{"email": "a@example.com"}], "subject": "Hola", "body_text": "Cuerpo"}
    r = client.post("/accounts/work/messages/send", headers=AUTH, json=body)
    assert r.status_code == 200
    name, args, kwargs = fake.calls[0]
    assert name == "send"
    assert args == ("work",)
    assert kwargs["to"] == [{"email": "a@example.com"}]
    assert kwargs["subject"] == "Hola"
    assert kwargs["body_text"] == "Cuerpo"


def test_reply_message(client, fake):
    body = {"body_text": "Respuesta", "reply_all": True}
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/reply", headers=AUTH, json=body
    )
    assert r.status_code == 200
    name, args, kwargs = fake.calls[0]
    assert name == "reply"
    assert args == ("work", "INBOX", "42", "Respuesta")
    assert kwargs["reply_all"] is True
    assert kwargs["include_original"] is True


def test_save_reply_draft(client, fake):
    body = {"body_text": "Borrador de respuesta"}
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/reply-draft", headers=AUTH, json=body
    )
    assert r.status_code == 200
    assert r.json() == {"folder_id": "Drafts", "message_id": "9", "sent": False}
    name, args, kwargs = fake.calls[0]
    assert name == "save_reply_draft"
    assert args == ("work", "INBOX", "42", "Borrador de respuesta")
    assert kwargs["reply_all"] is False


def test_forward_message(client, fake):
    body = {"recipients": ["a@example.com"], "body_text": "Fwd"}
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/forward", headers=AUTH, json=body
    )
    assert r.status_code == 200
    assert fake.calls == [
        ("forward", ("work", "INBOX", "42", ["a@example.com"], "Fwd"), {})
    ]


def test_forward_message_raw(client, fake):
    body = {"recipients": ["log@example.com"]}
    r = client.post(
        "/accounts/work/folders/INBOX/messages/42/forward-raw", headers=AUTH, json=body
    )
    assert r.status_code == 200
    assert fake.calls == [
        ("forward_raw", ("work", "INBOX", "42", ["log@example.com"]), {})
    ]


def test_save_draft(client, fake):
    body = {"recipients": [{"email": "a@example.com"}], "subject": "Borrador"}
    r = client.post("/accounts/work/drafts", headers=AUTH, json=body)
    assert r.status_code == 200
    name, args, kwargs = fake.calls[0]
    assert name == "save_draft"
    assert args == ("work",)
    assert kwargs["recipients"] == [{"email": "a@example.com"}]
    assert kwargs["subject"] == "Borrador"


# ==========================================================================
# Adjuntos
# ==========================================================================

def test_list_attachments(client, fake):
    r = client.get(
        "/accounts/work/folders/INBOX/messages/42/attachments", headers=AUTH
    )
    assert r.status_code == 200
    assert fake.calls == [("list_attachments", ("work", "INBOX", "42"), {})]


def test_download_attachment_devuelve_binario(client, fake):
    r = client.get(
        "/accounts/work/folders/INBOX/messages/42/attachments/a1", headers=AUTH
    )
    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="doc.pdf"' in r.headers["content-disposition"]
    assert fake.calls == [("download_attachment", ("work", "INBOX", "42", "a1"), {})]


def test_download_attachment_no_encontrado_da_404(client, fake):
    fake.raise_next(AttachmentNotFoundError("no existe"))
    r = client.get(
        "/accounts/work/folders/INBOX/messages/42/attachments/missing", headers=AUTH
    )
    assert r.status_code == 404


# ==========================================================================
# Mapeo de errores
# ==========================================================================

def test_account_not_found_da_404(client, fake):
    fake.raise_next(AccountNotFoundError("no existe"))
    r = client.get("/accounts/ghost", headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"error": "no existe"}


def test_message_not_found_da_404(client, fake):
    fake.raise_next(MessageNotFoundError("no existe"))
    r = client.get("/accounts/work/folders/INBOX/messages/missing", headers=AUTH)
    assert r.status_code == 404


def test_provider_error_da_502(client, fake):
    fake.raise_next(ProviderError("fallo el proveedor"))
    r = client.get("/accounts/work/folders", headers=AUTH)
    assert r.status_code == 502


def test_config_error_da_500(client, fake):
    fake.raise_next(ConfigError("config inválida"))
    r = client.get("/accounts/work/folders", headers=AUTH)
    assert r.status_code == 500


def test_excepcion_generica_da_500_sin_detalle(client, fake):
    fake.raise_next(RuntimeError("detalle interno sensible"))
    r = client.get("/accounts/work/folders", headers=AUTH)
    assert r.status_code == 500
    assert "detalle interno sensible" not in r.text


def test_falta_campo_requerido_da_400(client, fake):
    r = client.post("/accounts/work/folders", headers=AUTH, json={})
    assert r.status_code == 400
