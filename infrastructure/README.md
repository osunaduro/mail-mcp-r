# Infraestructura y despliegue

Esta carpeta construye y ejecuta el servidor MCP de correo en Docker, en modo remoto: accesible desde fuera de esta máquina, detrás de `meka-infra` (Cloudflare Tunnel → Nginx Proxy Manager → red Docker compartida `meka-network`).

## Requisitos

- Docker Engine con Docker Compose.
- La red Docker externa `meka-network` (la crea `meka-infra`).
- Un `accounts.yaml` con las cuentas administradas (ver [`home/config/accounts.example.yaml`](../home/config/accounts.example.yaml)).

## Puesta en marcha

```bash
cd infrastructure/remote
cp .env.example .env
docker network create meka-network   # una sola vez, si no existe
```

Editá `.env` con la ruta al `accounts.yaml` del host y tu identidad (`id -u` / `id -g`):

```dotenv
MEKA_UID=1000
MEKA_GID=1000
MAIL_MCP_CONFIG_PATH=/srv/meka/mail-mcp/accounts.yaml
```

### Modo de autenticación

`MEKA_AUTH_MODE` admite `api-key` y `oidc`. Claude (web, Android, desktop) sólo acepta conectores MCP remotos vía OAuth, así que este proyecto usa `oidc` por defecto:

```dotenv
MEKA_AUTH_MODE=oidc
MEKA_OIDC_ISSUER=https://auth.mekaweb.com.ar/application/o/mail-mcp/
MEKA_OIDC_AUDIENCE=<client_id del Provider en Authentik>
MEKA_OIDC_JWKS_URL=https://auth.mekaweb.com.ar/application/o/mail-mcp/jwks/
MEKA_OIDC_RESOURCE_URL=https://mail.mekaweb.com.ar/mcp
```

Estos valores salen de crear un Provider/Application OAuth2 (confidential) en Authentik — ver [`remote/oidc-authentik-setup.md`](remote/oidc-authentik-setup.md) una vez creado.

Para otros clientes que no soporten OAuth, `api-key` sigue disponible:

```dotenv
MEKA_AUTH_MODE=api-key
MEKA_API_KEY=un-token-largo-y-secreto   # generar con ./generate-api-key.sh
```

### Levantar el servicio

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f mail-mcp
```

El contenedor escucha internamente en `/mcp/`, sin puerto publicado al host. El proxy inverso (Nginx Proxy Manager, en `meka-infra`) es responsable de conectar `mail.mekaweb.com.ar` a este servicio dentro de `meka-network` y de cumplir el contrato de la siguiente sección.

Detener el servicio no borra las cuentas configuradas, porque `accounts.yaml` vive en el host:

```bash
docker compose down
```

Para rotar la clave en modo `api-key`: generá un nuevo token, actualizá `MEKA_API_KEY` en `.env`, y volvé a `docker compose up -d`.

## Contrato para el proxy/túnel

La imagen corre Uvicorn con `--proxy-headers --forwarded-allow-ips "*"`, así que confía en los headers `X-Forwarded-*` que le lleguen. El proxy/túnel necesita:

1. **Reenviar el header `Authorization`** tal cual — sin esto, el servidor siempre responde `401` sin importar el modo de auth.
2. **Setear `X-Forwarded-Proto`** con el esquema real (`https`) — si no lo hace, algunos clientes MCP fallan al seguir redirects internos con esquema incorrecto.
3. Usar **HTTP/1.1** hacia el contenedor.
4. En modo `oidc`: reenviar también las rutas de discovery, en particular `/.well-known/oauth-protected-resource/mcp`, si el cliente MCP las necesita (por ejemplo Claude o ChatGPT).

## Diagnóstico

| Síntoma | Revisar |
| --- | --- |
| `401 Unauthorized` | Token ausente o distinto a `MEKA_API_KEY` (modo `api-key`). |
| `401` en modo `oidc` | Token JWT ausente, expirado, o `issuer`/`audience` no coinciden con el Provider de Authentik. |
| `403` en modo `oidc` | Token válido pero sin el scope requerido por la herramienta (`mail:read`, `mail:write`, `mail:delete`). |
| `503` | `MEKA_API_KEY` no llegó al contenedor (modo `api-key`). |
| El proxy no resuelve el servicio | El contenedor `mail-mcp` y `meka-proxy` deben compartir `meka-network`. |
| Redirect con esquema `http://` incorrecto | El proxy/túnel no está seteando `X-Forwarded-Proto`; ver el contrato más arriba. |
| Falla la lectura de `accounts.yaml` | Verificar `MAIL_MCP_CONFIG_PATH` en `.env` y permisos de lectura del archivo en el host. |
