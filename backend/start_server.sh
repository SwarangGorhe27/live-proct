#!/bin/bash
# Live Proctoring Backend - Production Startup Script

PROJECT_ROOT="/Users/swarang.gorhe/Documents/live_proctoring/backend"
PYTHON_BIN="$PROJECT_ROOT/backend_env/bin/python"
LOG_FILE="/tmp/proctoring_server.log"

echo "🚀 Starting Live Proctoring Backend..."
echo "Project: $PROJECT_ROOT"
echo "Log: $LOG_FILE"
echo ""

# Kill any existing process
pkill -f "uvicorn app.main" || true

# Start new server
cd "$PROJECT_ROOT"
$PYTHON_BIN -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2 \
  --log-level info \
  > "$LOG_FILE" 2>&1 &

SERVER_PID=$!
echo "✅ Server started with PID: $SERVER_PID"

# Wait and verify
sleep 2

# Check if server is running
if curl -s http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    echo "✅ Server is healthy and responding"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🌐 LIVE PROCTORING API - PRODUCTION"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "📍 Server URL: http://0.0.0.0:8000"
    echo "📍 Localhost: http://127.0.0.1:8000"
    echo ""
    echo "📋 Available Endpoints:"
    echo "  • GET  /api/health              - Health check"
    echo "  • GET  /api/clients             - List active clients"
    echo "  • POST /api/session/start       - Start session"
    echo "  • POST /api/session/end         - End session"
    echo "  • GET  /api/violations/{id}     - Get violations"
    echo "  • GET  /api/report/{id}         - Get report"
    echo "  • WS   /ws/{id}                 - WebSocket stream"
    echo ""
    echo "📊 View logs with:"
    echo "  tail -f $LOG_FILE"
    echo ""
    echo "🛑 Stop server with:"
    echo "  pkill -f 'uvicorn app.main'"
    echo ""
    echo "✅ READY FOR PRODUCTION! 🚀"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Server failed to start. Check logs:"
    tail -20 "$LOG_FILE"
    exit 1
fi
