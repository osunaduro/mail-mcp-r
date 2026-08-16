# README_ARCHITECTURE

Visión de una sola mirada de la arquitectura de `mail-mcp-r`.

## Diagrama

```
Consumer
   │  (usa alias de cuenta + entidades del dominio)
   ▼
MailService            ← API pública de la biblioteca (mail_core)
   │
   ├── Config          ← lee home/config/accounts.yaml (única fuente, admin)
   ├── Providers       ← imap_smtp (protocolos encapsulados, extensible)
   └── Domain          ← Account, Folder, Message, Attachment, Recipient
```

```
Aplicación → Servidor MCP → MailService → Provider → Servidor de correo
```

## Reglas que no se negocian

- **Alias**: único identificador público de una cuenta. Nunca correos, servidores ni credenciales.
- **Encapsulamiento**: toda complejidad (IMAP, SMTP, autenticación) vive en `Providers`. Nada se filtra fuera.
- **Un solo negocio**: el servidor MCP solo valida → llama → devuelve. No implementa lógica.
- **Sin secretos**: las credenciales nunca salen de `Config` (ni a logs, ni a respuestas, ni a errores).
- **IDs estables**: los `message_id` expuestos son UIDs de IMAP, no números de secuencia.

## Dónde está cada cosa

| Responsabilidad | Ubicación |
|---|---|
| Contrato público (API) | `mail_core/api/service.py` → `MailService` |
| Configuración de cuentas | `mail_core/config/` + `home/config/accounts.yaml` |
| Protocolos de correo | `mail_core/providers/` |
| Entidades de dominio | `mail_core/domain/` |
| Errores funcionales | `mail_core/errors.py` |
| Capa de exposición | `mcp_server/` (FastMCP) |

## Flujo de una operación

1. El consumidor pide operar sobre un alias.
2. `MailService` resuelve el alias → configuración → proveedor.
3. El proveedor ejecuta contra el servidor de correo.
4. El resultado se devuelve como entidad del dominio.
