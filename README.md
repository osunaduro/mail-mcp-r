# MEKA Mail MCP

Servidor MCP y biblioteca Python para administrar cuentas de correo (IMAP/SMTP) configuradas por un administrador. Permite listar carpetas, leer, buscar, enviar, responder, reenviar y administrar adjuntos, sin que el cliente MCP conozca nunca credenciales ni detalles de conexión.

El núcleo (`mail_core`) es una **biblioteca Python pura**, sin ninguna dependencia de MCP, HTTP ni Docker. Sobre ella se construyeron adaptadores que la exponen de dos formas:

- **STDIO local**, sin autenticación (el proceso confía en quien lo lanza) — para Claude Desktop, Claude Code, VS Code, Cursor, Windsurf.
- **HTTP remoto**, con autenticación por `api-key` o **OIDC** como *Resource Server* real (validando JWT contra un proveedor externo: Authentik, Keycloak, Auth0, Okta, Azure Entra ID…) — para exponerlo desde donde quieras, detrás de tu propio proxy o túnel. Claude web/Android/desktop, al conectarse como conector remoto, solo acepta OAuth.

## Características

- 22 herramientas MCP para cuentas, carpetas, mensajes, envío y adjuntos.
- Además del MCP, una **API REST plana** (`/api/v1/...`) con las mismas 22 operaciones, para automatizaciones del ecosistema que no hablan MCP (ver [API REST](#api-rest)).
- Múltiples cuentas de correo simultáneas, cada una identificada por un alias (nunca por su dirección de correo ni sus credenciales).
- Autenticación configurable en dos modos: `api-key` y `oidc`.
- Scopes `mail:read`, `mail:write` y `mail:delete` que controlan las herramientas en modo OIDC.
- Sin herramientas para crear/eliminar cuentas ni cambiar credenciales: esa administración es exclusiva del archivo `home/config/accounts.yaml`.

## Herramientas MCP

| Área | Herramientas |
| --- | --- |
| Cuentas | `list_accounts`, `get_account` |
| Carpetas | `list_folders`, `create_folder`, `rename_folder`, `delete_folder` |
| Mensajes | `list_messages`, `get_message`, `search_messages`, `move_message`, `copy_message`, `delete_message`, `mark_read`, `mark_flagged` |
| Envío | `send_message`, `reply_message`, `forward_message`, `forward_message_raw`, `save_draft`, `save_reply_draft` |
| Adjuntos | `list_attachments`, `download_attachment` |

Notas sobre algunas herramientas menos obvias:

- `list_messages` no trae el cuerpo del mensaje (para no traer contenido pesado en listados); usar `get_message` para leerlo completo.
- `download_attachment` devuelve el contenido del adjunto codificado en base64.
- `reply_message`/`forward_message` operan sobre un mensaje existente (`folder_id` + `message_id`), no requieren reconstruir destinatarios ni asunto a mano.
- `forward_message` reconstruye el mensaje desde cero (nuevo cuerpo, nuevos headers) — pensado para reenvío conversacional con comentario propio. `forward_message_raw` en cambio reenvía los bytes RFC822 **originales** sin tocarlos, con headers `Resent-*` (RFC 5322 §3.6.6) agregados: conserva adjuntos, HTML y headers intactos — pensado para archivar/auditar un correo tal cual (ej. reenviarlo a una cuenta de log antes de borrarlo).
- **Enviar vs. borrador:** `send_message`, `reply_message` y `forward_message` envían de inmediato. `save_draft` (mensaje nuevo) y `save_reply_draft` (respuesta a un mensaje existente, con destinatarios, `Re:` y encadenamiento armados solos) **no envían nada**: guardan el mensaje vía IMAP `APPEND` en la carpeta de Borradores para que una persona lo revise y lo envíe desde su cliente de correo. Devuelven `{folder_id, message_id, sent: false}`.
- **Copia en Enviados:** SMTP solo entrega el mensaje; la copia en Enviados la guarda el servidor MCP vía IMAP después de cada `send_message`/`reply_message`/`forward_message`. El resultado indica `saved_to_sent` y `sent_folder_id`; si guardar la copia falla, el envío igual se informa como hecho, con un `warning`. En Gmail y Office 365/Outlook no se guarda (el propio servidor ya la guarda y se duplicaría), salvo `save_sent: true`. `forward_message_raw` no guarda copia (es un reenvío de auditoría).
- Las carpetas de Borradores y Enviados se detectan solas (atributos SPECIAL-USE `\Drafts`/`\Sent` o nombres habituales: `Drafts`, `Borradores`, `Sent`, `Enviados`, `Sent Items`, `INBOX.Sent`…; si no existe ninguna se crea `Drafts`/`Sent`). Se pueden fijar por cuenta con `drafts_folder`/`sent_folder` en `options`.
- Todos los `message_id` son UIDs de IMAP: estables mientras el mensaje siga existiendo en esa carpeta.

## API REST

Además del MCP (pensado para clientes como Claude), el mismo servidor expone las
22 operaciones de `mail_core` como una **API REST plana** en `/api/v1/...` —
JSON sobre HTTP, sin protocolo MCP — para que otros servicios del ecosistema
(automatizaciones, integraciones, scripts) puedan operar sobre las cuentas de
correo sin hablar MCP.

**Por qué existe, y por qué expone todo:** `mail-mcp-r` es un servicio pensado
para un ecosistema, no una librería para importar en cada proyecto — si mañana
cambia el backend de correo (otro proveedor, otra biblioteca), los consumidores
de esta API no se enteran, porque solo hablan HTTP contra rutas estables. Y en
vez de un subconjunto curado de operaciones, se exponen las 22: distintas
automatizaciones futuras (propias o de terceros que se bajen el proyecto) van a
necesitar subconjuntos distintos, y no hay forma de anticiparlos todos hoy.

Toda ruta requiere `Authorization: Bearer {MAIL_SERVICE_TOKEN}` — un secreto
propio, independiente de `MEKA_API_KEY`/OIDC del MCP (ver
[infrastructure/README.md](infrastructure/README.md#api-rest-apiv1)).

| Área | Método | Ruta | Body / Query |
| --- | --- | --- | --- |
| Cuentas | `GET` | `/accounts` | — |
| | `GET` | `/accounts/{alias}` | — |
| Carpetas | `GET` | `/accounts/{alias}/folders` | — |
| | `POST` | `/accounts/{alias}/folders` | `{name}` |
| | `PATCH` | `/accounts/{alias}/folders/{folder_id}` | `{new_name}` |
| | `DELETE` | `/accounts/{alias}/folders/{folder_id}` | — |
| Mensajes | `GET` | `/accounts/{alias}/folders/{folder_id}/messages` | `?limit&offset` |
| | `GET` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}` | — |
| | `GET` | `/accounts/{alias}/folders/{folder_id}/messages/search` | `?q&limit` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/move` | `{dest_folder_id}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/copy` | `{dest_folder_id}` |
| | `DELETE` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}` | — |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/read` | `{read: bool = true}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/flag` | `{flagged: bool = true}` |
| Envío | `POST` | `/accounts/{alias}/messages/send` | `{to, subject, body_text, body_html, cc, bcc, attachments}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/reply` | `{body_text, reply_all, include_original}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/reply-draft` | `{body_text, reply_all, include_original}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/forward` | `{recipients, body_text}` |
| | `POST` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/forward-raw` | `{recipients}` |
| | `POST` | `/accounts/{alias}/drafts` | `{recipients, subject, body_text, body_html, cc, bcc, attachments}` |
| Adjuntos | `GET` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/attachments` | — |
| | `GET` | `/accounts/{alias}/folders/{folder_id}/messages/{message_id}/attachments/{attachment_id}` | — |

Diferencias deliberadas respecto al contrato MCP:

- Errores como status HTTP + `{"error": "..."}` (404 cuenta/carpeta/mensaje/adjunto no encontrado, 502 fallas del proveedor de correo, 500 error de configuración o interno, 400 el resto), en vez del envelope `{"ok": ..., "result": ...}` del MCP.
- `GET .../attachments/{attachment_id}` devuelve el **binario crudo** del adjunto (`Content-Type` real + `Content-Disposition: attachment`), no JSON+base64 — más idiomático para un consumidor HTTP que va a guardar el archivo directo.

## Uso local con STDIO

El proyecto soporta dos transportes MCP que comparten las mismas herramientas (definidas una sola vez en [`workspace/mcp_server/tools.py`](workspace/mcp_server/tools.py)):

- **STDIO** (`mcp_server.stdio`): ejecución local por `command` + `args`, para Claude Desktop, Claude Code, VS Code, Cursor y Windsurf.
- **HTTP/OAuth** (`mcp_server.http`): servidor remoto, para conectores remotos (Claude web/Android/desktop).

Instalar las dependencias:

```bash
cd workspace
python3 -m pip install -e .
```

Ejecutar el adaptador local directamente:

```bash
python3 workspace/mcp_server/stdio.py
```

O, con el paquete instalado:

```bash
mail-mcp-stdio
```

Registro en Claude Desktop (`~/.config/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mail-mcp": {
      "command": "python3",
      "args": ["/ruta/al/proyecto/workspace/mcp_server/stdio.py"]
    }
  }
}
```

El proceso local lee `home/config/accounts.yaml` del proyecto por defecto (o la ruta que indique `MAIL_MCP_CONFIG`, si se define). Como el transporte local es confiable, no exige autenticación HTTP.

## Inicio rápido con Docker (modo remoto)

Ver [infrastructure/README.md](infrastructure/README.md) para el detalle completo. El servidor queda accesible desde fuera de esta máquina, detrás de tu propio proxy inverso o túnel (Nginx, Cloudflare Tunnel…). Requiere una red Docker externa (`meka-network`) y `MEKA_AUTH_MODE=api-key` u `oidc`.

```bash
cd infrastructure/remote
cp .env.example .env && docker network create meka-network
# editar .env (MAIL_MCP_CONFIG_PATH, modo de auth), luego:
docker compose up -d --build
```

## Autenticación (modo HTTP)

`MEKA_AUTH_MODE` selecciona el mecanismo de autenticación del servidor HTTP. Los dos modos son excluyentes.

| Modo | Uso | Configuración |
| --- | --- | --- |
| `api-key` | Instalaciones personales o de prueba, clientes que no soporten OAuth. | `MEKA_API_KEY` |
| `oidc` | Por defecto en este proyecto. Necesario para conectores remotos de Claude (web/Android/desktop), que solo aceptan OAuth. | `MEKA_OIDC_ISSUER`, `MEKA_OIDC_AUDIENCE`, `MEKA_OIDC_JWKS_URL`, `MEKA_OIDC_RESOURCE_URL` |

### Modo oidc

MEKA Mail actúa únicamente como *Resource Server*; la autenticación es responsabilidad del proveedor OIDC. No emite tokens ni gestiona usuarios.

El servidor valida la firma del JWT contra el JWKS, `issuer`, `audience` y expiración, y exige uno de tres scopes por herramienta:

| Scope | Herramientas |
| --- | --- |
| `mail:read` | Cuentas, carpetas, listar/leer/buscar mensajes, listar/descargar adjuntos. |
| `mail:write` | Crear/renombrar carpetas, mover/copiar mensajes, marcar leído/destacado, enviar, responder, reenviar, guardar borrador (nuevo o de respuesta). |
| `mail:delete` | Eliminar carpetas y mensajes. |

Publica además `/.well-known/oauth-protected-resource/mcp` para el descubrimiento MCP.

### Modo api-key

```dotenv
MEKA_AUTH_MODE=api-key
MEKA_API_KEY=un-token-largo-y-secreto
```

Cada solicitud HTTP debe enviar `Authorization: Bearer <MEKA_API_KEY>`. El servidor responde `401` si falta el token, no usa el esquema `Bearer` o no coincide.

## Configuración de cuentas

Un único archivo YAML (`home/config/accounts.yaml`, ver [`accounts.example.yaml`](home/config/accounts.example.yaml)) define todas las cuentas administradas — nunca se crean, eliminan ni modifican credenciales desde una herramienta MCP:

```yaml
accounts:
  alias-de-la-cuenta:
    name: "Nombre visible"
    email: "correo@dominio.com"
    provider: imap_smtp
    options:
      imap_host: "imap.dominio.com"
      imap_port: 993
      imap_ssl: true
      smtp_host: "smtp.dominio.com"
      smtp_port: 465
      smtp_ssl: true
      username: "correo@dominio.com"
      password: "contraseña-o-app-password"
```

El único `provider` implementado hoy es `imap_smtp`. Si la cuenta tiene 2FA activado, `password` debe ser una contraseña de aplicación.

## Estructura

```text
workspace/
  mail_core/          Biblioteca pura: cuentas, dominio, providers (IMAP/SMTP), errores — sin transporte
  mcp_server/          tools.py (herramientas MCP), rest_api.py (API REST), service.py/auth.py (compartido),
                        stdio.py (STDIO), http.py (HTTP/OAuth), app.py (combina MCP+REST), config.py
infrastructure/
  remote/              Docker Compose para exponer el servidor a internet (detrás de tu propio proxy/túnel)
home/
  config/              accounts.yaml (real, no versionado) y accounts.example.yaml
docs/                  Especificación funcional y técnica del proyecto
```

## Documentación

- [Documentación funcional y técnica (docs/)](docs)
- [Infraestructura (modo remoto)](infrastructure/README.md)
- [Servidores MCP](workspace/mcp_server/README.md)

## Desarrollo

El proyecto requiere Python 3.11 o superior. Sus dependencias de ejecución están definidas en `workspace/pyproject.toml`.

Instalar las dependencias de test y ejecutar la suite:

```bash
cd workspace
python3 -m pip install -e '.[test]'
python3 -m pytest -q
```

## Contacto

¿Dudas, bugs o sugerencias? Abrí un Issue en este repositorio.

## Licencia

MIT © 2026 MEKAweb (Martín Osuna). Ver [LICENSE](LICENSE).
