# OIDC — MEKA Mail en Authentik

Provider/Application creados en Authentik (`https://auth.mekaweb.com.ar`) para exponer `mail.mekaweb.com.ar` a clientes OAuth (Claude web/Android/desktop).

- Application slug: `mail-mcp`
- Provider: "MEKA Mail" (OAuth2/OpenID Provider)
- Client type: confidential
- Client ID: `7z3RJyWKvRNuZgEowuHSggxt6ORyi2OQKeAbosVk`
- Client Secret: no versionado — ver [`oidc-credentials.local.md`](oidc-credentials.local.md) (gitignored) en esta misma carpeta, o consultarlo directamente en el Provider "MEKA Mail" dentro de Authentik.
- Redirect URI configurado: regex `^https://claude\.ai/.*$` (mismo patrón provisorio que MEKA Filesystem — Authentik 2025.2.4 no soporta registro dinámico de clientes; si el redirect falla al agregar el conector, ajustar el regex a la ruta exacta del error).
- Scope Mappings custom creados (Personalización → Asignaciones de propiedades): `mail-mcp: mail:read`, `mail-mcp: mail:write`, `mail-mcp: mail:delete`, agregados a "Selected Scopes" del provider junto a los `openid`/`email`/`profile` por defecto. El servidor exige estos scopes por herramienta cuando `MEKA_AUTH_MODE=oidc` (ver `mcp_server/tools.py` y `mcp_server/http.py`).

`mail-mcp` corre en modo `oidc` (`infrastructure/remote/.env`):

```
MEKA_OIDC_ISSUER=https://auth.mekaweb.com.ar/application/o/mail-mcp/
MEKA_OIDC_AUDIENCE=7z3RJyWKvRNuZgEowuHSggxt6ORyi2OQKeAbosVk
MEKA_OIDC_JWKS_URL=https://auth.mekaweb.com.ar/application/o/mail-mcp/jwks/
MEKA_OIDC_RESOURCE_URL=https://mail.mekaweb.com.ar/mcp
```

`MEKA_OIDC_AUDIENCE` es el `client_id` (no una URL) porque Authentik en esta versión no soporta "resource indicators" (RFC 8707) — el claim `aud` del JWT que emite es siempre el client_id. El `client_secret` **no** se usa en este `.env`: lo valida la parte que hace el intercambio `authorization_code` (Claude), no el servidor de recursos (`mail-mcp`), que sólo verifica firma/issuer/audience vía JWKS.

## Para agregar el conector en Claude (web, Android, desktop)

1. En claude.ai: Configuración → Conectores → Agregar conector personalizado.
2. URL: `https://mail.mekaweb.com.ar/mcp/`
3. Si pide iniciar sesión automáticamente (vía descubrimiento OAuth): debería redirigir a Authentik para loguearte con el usuario admin (`proyectos@mekaweb.com.ar`) u otro usuario que se cree ahí.
4. Si pide Client ID / Client Secret manualmente (esperable, por la falta de auto-registro): usar los valores de arriba.
5. Si el login redirige mal o da error de "redirect_uri inválida": ajustar el regex del Provider en Authentik con la URL exacta del error.

## Pendiente

- No hay pendientes de despliegue: el flujo OAuth funciona end-to-end, verificado con Claude Desktop y web.
