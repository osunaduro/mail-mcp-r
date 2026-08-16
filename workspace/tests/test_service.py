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
