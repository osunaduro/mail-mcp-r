"""Carga y validación del archivo de configuración.

La configuración es la única fuente autorizada para definir las cuentas.
Su lectura es responsabilidad exclusiva de la biblioteca; ningún otro
componente accede a este archivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mail_core.errors import ConfigError

REQUIRED_ACCOUNT_FIELDS = ("name", "provider")


@dataclass(frozen=True)
class AccountConfig:
    """Configuración interna de una cuenta. Nunca se expone públicamente."""

    alias: str
    name: str
    provider: str
    email: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def _require(self, key: str) -> str:
        value = self.options.get(key)
        if not value:
            raise ConfigError(
                f"La cuenta '{self.alias}' no define el parámetro requerido '{key}'."
            )
        return value

    @property
    def credentials(self) -> dict[str, Any]:
        return self.options.get("credentials", {})


@dataclass(frozen=True)
class MailConfig:
    """Conjunto de cuentas configuradas, indexado por alias."""

    accounts: dict[str, AccountConfig] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "MailConfig":
        cfg_path = Path(path)
        if not cfg_path.exists():
            raise ConfigError(f"No se encontró el archivo de configuración: {path}")

        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError("El archivo de configuración tiene un formato YAML inválido.") from exc
        except OSError as exc:
            raise ConfigError(f"No se pudo leer el archivo de configuración: {path}") from exc

        if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), dict):
            raise ConfigError("El archivo de configuración debe contener una sección 'accounts'.")

        accounts: dict[str, AccountConfig] = {}
        for alias, data in raw["accounts"].items():
            if not isinstance(data, dict):
                raise ConfigError(f"La cuenta '{alias}' debe ser un mapa de configuración.")
            account = cls._validate_account(str(alias), data)
            accounts[account.alias] = account

        if not accounts:
            raise ConfigError("El archivo de configuración no define ninguna cuenta.")

        return cls(accounts=accounts)

    @classmethod
    def _validate_account(cls, alias: str, data: dict[str, Any]) -> AccountConfig:
        for field_name in REQUIRED_ACCOUNT_FIELDS:
            if field_name not in data or not str(data[field_name]).strip():
                raise ConfigError(
                    f"La cuenta '{alias}' no define el campo obligatorio '{field_name}'."
                )

        provider = str(data["provider"]).strip()
        options = data.get("options")
        if not isinstance(options, dict):
            raise ConfigError(f"La cuenta '{alias}' debe definir la sección 'options'.")

        email = data.get("email")
        if email is not None and not isinstance(email, str):
            raise ConfigError(f"La cuenta '{alias}' tiene un 'email' inválido.")

        return AccountConfig(
            alias=alias,
            name=str(data["name"]),
            provider=provider,
            email=email,
            options=options,
        )
