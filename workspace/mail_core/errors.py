"""Jerarquía de errores funcionales de la biblioteca.

Todos los errores que llegan a la API pública derivan de ``MailCoreError``.
Nunca se exponen detalles internos de protocolos, proveedores o credenciales.
"""

from __future__ import annotations


class MailCoreError(Exception):
    """Error base de la biblioteca. Mensaje funcional y seguro."""


class ConfigError(MailCoreError):
    """Error al cargar o validar el archivo de configuración."""


class ProviderError(MailCoreError):
    """Error genérico del proveedor de correo."""


class AccountNotFoundError(MailCoreError):
    """La cuenta solicitada no existe entre las configuradas."""


class FolderNotFoundError(MailCoreError):
    """La carpeta solicitada no existe en la cuenta."""


class MessageNotFoundError(MailCoreError):
    """El mensaje solicitado no existe en la carpeta."""


class AttachmentNotFoundError(MailCoreError):
    """El adjunto solicitado no existe en el mensaje."""


class AuthenticationError(ProviderError):
    """Error de autenticación contra el servidor de correo."""


class ConnectionError(ProviderError):
    """No se pudo establecer comunicación con el servidor de correo."""


class SendError(ProviderError):
    """Error al enviar un mensaje."""
