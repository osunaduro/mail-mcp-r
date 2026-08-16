import pytest

from mail_core.errors import ConfigError
from mail_core.config.config import MailConfig


def test_carga_config_valida(tmp_path):
    cfg = tmp_path / "accounts.yaml"
    cfg.write_text(
        """
accounts:
  work:
    name: "Correo de trabajo"
    email: "work@example.com"
    provider: imap_smtp
    options:
      imap_host: "imap.example.com"
      username: "work@example.com"
      password: "secret"
""",
        encoding="utf-8",
    )
    config = MailConfig.load(cfg)
    assert "work" in config.accounts
    account = config.accounts["work"]
    assert account.name == "Correo de trabajo"
    assert account.provider == "imap_smtp"
    assert account.options["imap_host"] == "imap.example.com"


def test_carga_config_inexistente():
    with pytest.raises(ConfigError):
        MailConfig.load("/no/existe/accounts.yaml")


def test_carga_config_sin_accounts(tmp_path):
    cfg = tmp_path / "accounts.yaml"
    cfg.write_text("accounts: {}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        MailConfig.load(cfg)


def test_cuenta_falta_campo_obligatorio(tmp_path):
    cfg = tmp_path / "accounts.yaml"
    cfg.write_text(
        """
accounts:
  bad:
    provider: imap_smtp
    options:
      imap_host: "imap.example.com"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="obligatorio"):
        MailConfig.load(cfg)


def test_cuenta_sin_options(tmp_path):
    cfg = tmp_path / "accounts.yaml"
    cfg.write_text(
        """
accounts:
  bad:
    name: "Sin options"
    provider: imap_smtp
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="options"):
        MailConfig.load(cfg)
