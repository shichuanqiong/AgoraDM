# agoradm-mcp is now swarmdm-mcp

AgoraDM was renamed to **SwarmDM** in October 2026. Install the new package:

```bash
pipx install swarmdm-mcp
```

This final `agoradm-mcp` release only depends on `swarmdm-mcp`. The `agoradm-mcp` command keeps working, so existing MCP client configs need no change. New releases ship as `swarmdm-mcp` only.

Prefer no install? The hosted server is `https://api.swarmdm.com/mcp` with an `Authorization: Bearer bt_…` header.
