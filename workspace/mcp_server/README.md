# Servidor MCP

Este paquete contiene los adaptadores de transporte para el dominio de correo.
Cada adaptador crea una aplicación FastMCP que expone las mismas 20 herramientas,
definidas una sola vez en `tools.py`.

## Contenido

| Archivo | Transporte | Uso |
| --- | --- | --- |
| `tools.py` | — | Definición compartida de las 20 herramientas y helpers de serialización. |
| `config.py` | — | Variables de entorno de transporte/autenticación (`MEKA_AUTH_MODE`, `MEKA_API_KEY`, `MEKA_OIDC_*`). No define nada del dominio de correo. |
| `stdio.py` | STDIO | Punto de entrada local para Claude Desktop, Claude Code, VS Code, Cursor, Windsurf. |
| `http.py` | HTTP / OAuth | Servidor remoto ejecutado con Uvicorn, para conectores remotos (Claude web/Android/desktop). |

## Responsabilidades

- Exponen las mismas 20 herramientas MCP en ambos transportes.
- Obtienen `MailService` a partir de `MAIL_MCP_CONFIG` (o `home/config/accounts.yaml` por defecto si no se define).
- Validan parámetros, invocan `mail_core` y devuelven el resultado — no implementan lógica de negocio propia.
- El adaptador HTTP autentica cada solicitud según `MEKA_AUTH_MODE`:
  - `api-key`: exige `Authorization: Bearer <MEKA_API_KEY>` mediante `BearerTokenMiddleware`.
  - `oidc`: actúa como *Resource Server* OAuth, valida el JWT con el proveedor y exige los scopes `mail:read`, `mail:write` y `mail:delete` por herramienta.
- El adaptador STDIO no autentica: el proceso local es el cliente autorizado.

Los servidores no implementan por su cuenta las operaciones de correo: delegan
todo en `mail_core.MailService`. Esto mantiene la lógica de dominio (IMAP/SMTP,
parseo de mensajes, validación de configuración) centralizada y reutilizable
sin exponer una red.

En modo `oidc` el adaptador HTTP publica
`/.well-known/oauth-protected-resource/mcp` para el descubrimiento MCP. El
detalle del proveedor configurado está en
[infrastructure/remote/oidc-authentik-setup.md](../../infrastructure/remote/oidc-authentik-setup.md).

La ejecución de producción del transporte HTTP está definida en
[infrastructure/remote/docker-compose.yml](../../infrastructure/remote/docker-compose.yml).
