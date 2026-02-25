FROM node:22-slim

RUN npm install -g mcp-proxy @modelcontextprotocol/server-sequential-thinking

EXPOSE 8001

CMD ["mcp-proxy", "--host", "0.0.0.0", "--port", "8001", "--", "mcp-server-sequential-thinking"]
