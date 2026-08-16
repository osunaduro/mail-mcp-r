# Servidor MCP

Este paquete contiene los adaptadores de transporte para el dominio de correo.
Cada adaptador MCP crea una aplicación FastMCP que expone las mismas 21
herramientas, definidas una sola vez en `tools.py`. En paralelo, `rest_api.py`
expone las mismas 21 operaciones como una API REST plana (`/api/v1/...`) para
consumidores que no hablan MCP.

## Contenido

| Archivo | Transporte | Uso |
| --- | --- | --- |
| `tools.py` | MCP | Definición compartida de las 21 herramientas y helpers de serialización. |
| `rest_api.py` | REST | API REST plana (`/api/v1/...`) sobre las mismas 21 operaciones de `MailService`. |
| `service.py` | — | Punto único de acceso al `MailService` compartido (resuelve `MAIL_MCP_CONFIG`), usado tanto por `tools.py` como por `rest_api.py`. |
| `auth.py` | — | `BearerTokenMiddleware`, parametrizable por token — usado por `http.py` (`MEKA_API_KEY`) y `rest_api.py` (`MAIL_SERVICE_TOKEN`), cada uno con su propio secreto. |
| `config.py` | — | Variables de entorno de transporte/autenticación (`MEKA_AUTH_MODE`, `MEKA_API_KEY`, `MEKA_OIDC_*`, `MAIL_SERVICE_TOKEN`). No define nada del dominio de correo. |
| `stdio.py` | STDIO | Punto de entrada local para Claude Desktop, Claude Code, VS Code, Cursor, Windsurf. |
| `http.py` | HTTP / OAuth | Servidor MCP remoto ejecutado con Uvicorn, para conectores remotos (Claude web/Android/desktop). |
| `app.py` | HTTP | Punto de entrada de producción: monta `http.py` (MCP, en `/`) y `rest_api.py` (REST, en `/api/v1`) en el mismo proceso/contenedor. |

## Responsabilidades

- Exponen las mismas 21 herramientas MCP en ambos transportes MCP, y las mismas 21 operaciones vía REST en `/api/v1/...`.
- Obtienen `MailService` a partir de `MAIL_MCP_CONFIG` (o `home/config/accounts.yaml` por defecto si no se define) — vía `service.get_service()`, una sola fuente de verdad compartida por MCP y REST.
- Validan parámetros, invocan `mail_core` y devuelven el resultado — no implementan lógica de negocio propia.
- El adaptador HTTP (MCP) autentica cada solicitud según `MEKA_AUTH_MODE`:
  - `api-key`: exige `Authorization: Bearer <MEKA_API_KEY>` mediante `BearerTokenMiddleware`.
  - `oidc`: actúa como *Resource Server* OAuth, valida el JWT con el proveedor y exige los scopes `mail:read`, `mail:write` y `mail:delete` por herramienta.
- La API REST siempre exige `Authorization: Bearer <MAIL_SERVICE_TOKEN>` (mismo `BearerTokenMiddleware`, secreto propio), sin importar el `MEKA_AUTH_MODE` del MCP.
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
