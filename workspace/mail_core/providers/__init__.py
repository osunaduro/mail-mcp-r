"""Proveedores de correo registrados."""

from mail_core.providers.base import Provider
from mail_core.providers.registry import available_providers, create_provider, register
import mail_core.providers.imap_smtp  # noqa: F401  (registra imap_smtp)

__all__ = ["Provider", "create_provider", "register", "available_providers"]
