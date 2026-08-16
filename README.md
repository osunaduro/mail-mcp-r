# MEKA Mail MCP

Servidor MCP y biblioteca Python para administrar cuentas de correo (IMAP/SMTP) configuradas por un administrador. Permite listar carpetas, leer, buscar, enviar, responder, reenviar y administrar adjuntos, sin que el cliente MCP conozca nunca credenciales ni detalles de conexión.

El núcleo (`mail_core`) es una **biblioteca Python pura**, sin ninguna dependencia de MCP, HTTP ni Docker. Sobre ella se construyeron adaptadores que la exponen de dos formas:

- **STDIO local**, sin autenticación (el proceso confía en quien lo lanza) — para Claude Desktop, Claude Code, VS Code, Cursor, Windsurf.
- **HTTP remoto**, con autenticación por `api-key` o **OIDC** como *Resource Server* real (validando JWT contra un proveedor externo: Authentik, Keycloak, Auth0, Okta, Azure Entra ID…) — para exponerlo desde donde quieras, detrás de tu propio proxy o túnel. Claude web/Android/desktop, al conectarse como conector remoto, solo acepta OAuth.

## Características

- 20 herramientas MCP para cuentas, carpetas, mensajes, envío y adjuntos.
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
| Envío | `send_message`, `reply_message`, `forward_message`, `save_draft` |
| Adjuntos | `list_attachments`, `download_attachment` |

Notas sobre algunas herramientas menos obvias:

- `list_messages` no trae el cuerpo del mensaje (para no traer contenido pesado en listados); usar `get_message` para leerlo completo.
- `download_attachment` devuelve el contenido del adjunto codificado en base64.
- `reply_message`/`forward_message` operan sobre un mensaje existente (`folder_id` + `message_id`), no requieren reconstruir destinatarios ni asunto a mano.
- Todos los `message_id` son UIDs de IMAP: estables mientras el mensaje siga existiendo en esa carpeta.

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
| `mail:write` | Crear/renombrar carpetas, mover/copiar mensajes, marcar leído/destacado, enviar, responder, reenviar, guardar borrador. |
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
  mcp_server/          tools.py (herramientas compartidas), stdio.py (STDIO), http.py (HTTP/OAuth), config.py
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
