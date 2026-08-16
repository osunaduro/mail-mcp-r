"""Registro de proveedores.

Permite incorporar nuevos mecanismos de comunicación por extensión:
basta con registrar una nueva fábrica bajo un nombre de proveedor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from mail_core.errors import ConfigError

if TYPE_CHECKING:
    from mail_core.config.config import AccountConfig
    from mail_core.providers.base import Provider


ProviderFactory = Callable[["AccountConfig"], "Provider"]

_registry: dict[str, ProviderFactory] = {}


def register(provider_name: str) -> Callable[[ProviderFactory], ProviderFactory]:
    """Decorador para registrar la fábrica de un proveedor."""

    def decorator(factory: ProviderFactory) -> ProviderFactory:
        _registry[provider_name] = factory
        return factory

    return decorator


def create_provider(config: "AccountConfig") -> "Provider":
    """Instancia el proveedor adecuado para una configuración de cuenta."""
    factory = _registry.get(config.provider)
    if factory is None:
        raise ConfigError(
            f"La cuenta '{config.alias}' usa un proveedor no soportado: '{config.provider}'."
        )
    return factory(config)


def available_providers() -> list[str]:
    return sorted(_registry)
