"""mail_core: biblioteca de gestión de correo electrónico.

Núcleo funcional del proyecto. Expone la API pública mediante ``MailService``
y encapsula toda la complejidad técnica de los distintos proveedores.
"""

from mail_core.api.service import MailService
from mail_core.errors import (
    AccountNotFoundError,
    AuthenticationError,
    ConfigError,
    ConnectionError as MailConnectionError,
    FolderNotFoundError,
    MailCoreError,
    MessageNotFoundError,
    ProviderError,
    SendError,
)

__all__ = [
    "MailService",
    "MailCoreError",
    "ConfigError",
    "ProviderError",
    "AccountNotFoundError",
    "FolderNotFoundError",
    "MessageNotFoundError",
    "AuthenticationError",
    "MailConnectionError",
    "SendError",
]