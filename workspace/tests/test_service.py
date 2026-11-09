import pytest

from mail_core import AccountNotFoundError, MailService
from mail_core.providers.registry import available_providers


def _write_config(tmp_path, name="work", **extra):
    cfg = tmp_path / "accounts.yaml"
    lines = [
        "accounts:",
        f'  {name}:',
        f'    name: "Correo {name}"',
        '    provider: imap_smtp',
        '    options:',
        '      imap_host: "imap.example.com"',
        '      smtp_host: "smtp.example.com"',
        '      username: "user@example.com"',
        '      password: "secret"',
    ]
    for key, value in extra.items():
        lines.append(f"      {key}: {value}")
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


def test_list_accounts_y_get_account(tmp_path):
    svc = MailService(_write_config(tmp_path))
    accounts = svc.list_accounts()
    assert len(accounts) == 1
    assert accounts[0].alias == "work"
    assert svc.get_account("work")["name"] == "Correo work"


def test_get_account_inexistente(tmp_path):
    svc = MailService(_write_config(tmp_path))
    with pytest.raises(AccountNotFoundError):
        svc.get_account("no-existe")


def test_proveedor_registrado_para_cuenta(tmp_path):
    assert "imap_smtp" in available_providers()


def test_dos_cuentas_multiples_alias(tmp_path):
    cfg = tmp_path / "accounts.yaml"
    cfg.write_text(
        """
accounts:
  a:
    name: "A"
    provider: imap_smtp
    options:
      username: "a@example.com"
      password: "x"
  b:
    name: "B"
    provider: imap_smtp
    options:
      username: "b@example.com"
      password: "y"
""",
        encoding="utf-8",
    )
    svc = MailService(cfg)
    assert {a.alias for a in svc.list_accounts()} == {"a", "b"}


# -- Adjuntos: data_base64 -------------------------------------------------

def _send_capturando_draft(tmp_path, attachments):
    class _Sent:
        def to_dict(self):
            return {}

    class _Provider:
        draft = None

        def send(self, draft):
            self.draft = draft
            return _Sent()

    svc = MailService(_write_config(tmp_path))
    provider = _Provider()
    svc._provider_for = lambda alias: provider
    svc.send("work", to=[{"email": "a@example.com"}], attachments=attachments)
    return provider.draft


def test_adjunto_data_base64_llega_como_bytes_exactos(tmp_path):
    import base64

    pdf = b"%PDF-1.4\xff\xfe"
    draft = _send_capturando_draft(
        tmp_path,
        [{"filename": "a.pdf", "data_base64": base64.b64encode(pdf).decode(), "content_type": "application/pdf"}],
    )
    assert draft.attachments == [("a.pdf", pdf, "application/pdf")]


def test_adjunto_data_texto_sigue_igual(tmp_path):
    draft = _send_capturando_draft(tmp_path, [{"filename": "a.txt", "data": "hola ñ"}])
    assert draft.attachments == [("a.txt", "hola ñ".encode("utf-8"), None)]


def test_adjunto_data_base64_invalido_da_value_error(tmp_path):
    with pytest.raises(ValueError, match="data_base64"):
        _send_capturando_draft(tmp_path, [{"filename": "a.pdf", "data_base64": "no es base64!!"}])
