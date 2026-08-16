# Workspace

Código Python del proyecto. Se divide en una biblioteca reutilizable de correo y el adaptador de red MCP.

```text
workspace/
├── mail_core/    Biblioteca pura: dominio, configuración, providers (IMAP/SMTP), errores
└── mcp_server/   Adaptadores STDIO y HTTP/OAuth que exponen mail_core como herramientas MCP
```

## Capas

- [mail_core/](mail_core) no depende de MCP, HTTP ni Docker. Su API pública es `MailService`; recibe la ruta a un `accounts.yaml` y expone operaciones sobre alias de cuenta, nunca sobre credenciales.
- [mcp_server/](mcp_server/README.md) adapta la biblioteca a herramientas MCP y aplica autenticación HTTP cuando corresponde.

Las dependencias fluyen desde `mcp_server` hacia `mail_core`; la biblioteca no depende del servidor. Ningún componente fuera de `mail_core.config` lee `accounts.yaml` directamente.
