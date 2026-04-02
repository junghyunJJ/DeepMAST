#!/bin/bash
# Start biomcp MCP server on port 8000 (Streamable HTTP)
# Matches docker-compose port: 8000:8000

PORT=8000
LOG=/tmp/biomcp.log
NAME="biomcp"

# Kill existing process on the port if any
PID=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$PID" ]; then
    echo "[$NAME] Killing existing process on port $PORT (PID: $PID)"
    kill $PID 2>/dev/null
    sleep 1
fi

echo "[$NAME] Starting on port $PORT..."
echo "[$NAME] Log: $LOG"

nohup biomcp run --mode streamable_http --host 0.0.0.0 --port $PORT > "$LOG" 2>&1 &
echo "[$NAME] PID: $!"
echo "[$NAME] Endpoint: http://localhost:$PORT/mcp"
