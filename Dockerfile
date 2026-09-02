# MCP server image — used by directory crawlers (Glama) to verify the
# server starts and answers introspection. Runtime users normally just
# `pip install agoradm-mcp` and run the `agoradm-mcp` entry point.
FROM python:3.12-slim
RUN pip install --no-cache-dir agoradm-mcp==0.2.1
# stdio transport; A2ADM_TOKEN is only needed at first tool call, so
# introspection works without secrets.
ENTRYPOINT ["agoradm-mcp"]
