#!/bin/bash
# Start sequential-thinking MCP server on port 8001 (Streamable HTTP)
# Matches docker-compose port: 8001:8001

PORT=8001
LOG=/tmp/sequentialthinking.log
NAME="sequentialthinking"

# Kill existing process on the port if any
PID=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$PID" ]; then
    echo "[$NAME] Killing existing process on port $PORT (PID: $PID)"
    kill $PID 2>/dev/null
    sleep 1
fi

echo "[$NAME] Starting on port $PORT..."
echo "[$NAME] Log: $LOG"

nohup npx -y supergateway \
    --stdio "npx -y @modelcontextprotocol/server-sequential-thinking" \
    --outputTransport streamableHttp \
    --port $PORT \
    --streamableHttpPath /mcp \
    > "$LOG" 2>&1 &
echo "[$NAME] PID: $!"
echo "[$NAME] Endpoint: http://localhost:$PORT/mcp"
