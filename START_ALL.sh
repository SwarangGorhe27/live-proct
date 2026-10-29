#!/bin/bash
# Live Proctoring - macOS Quick Start
# This script starts both backend and frontend servers

echo "========================================"
echo "Live Proctoring System - macOS Startup"
echo "========================================"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Function to start backend
start_backend() {
    cd "$SCRIPT_DIR/backend"
    
    # Check if virtual environment exists
    if [ ! -d "backend_env" ]; then
        echo "Creating Python virtual environment..."
        python3 -m venv backend_env
    fi
    
    # Activate virtual environment
    source backend_env/bin/activate
    
    # Install requirements if needed
    if ! pip show uvicorn > /dev/null 2>&1; then
        echo "Installing Python dependencies..."
        pip install -r requirements.txt
    fi
    
    # Start backend
    echo ""
    echo "Starting FastAPI backend server..."
    echo "Backend will be available at: http://127.0.0.1:8000"
    echo "Press Ctrl+C to stop backend"
    echo ""
    
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
}

# Function to start frontend
start_frontend() {
    cd "$SCRIPT_DIR/frontend"
    
    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        echo "Installing Node dependencies..."
        npm install
    fi
    
    # Start frontend
    echo ""
    echo "Starting React frontend server..."
    echo "Frontend will be available at: http://localhost:3000"
    echo "Browser will open automatically"
    echo "Press Ctrl+C to stop frontend"
    echo ""
    
    npm start
}

# Start both servers in background
echo "Starting backend server in new terminal..."
osascript <<EOF
tell application "Terminal"
    activate
    do script "cd '$SCRIPT_DIR' && bash -c 'source backend/backend_env/bin/activate 2>/dev/null; python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload' || bash"
end tell
EOF

sleep 3

echo "Starting frontend server in new terminal..."
osascript <<EOF
tell application "Terminal"
    activate
    do script "cd '$SCRIPT_DIR/frontend' && npm start"
end tell
EOF

echo ""
echo "========================================"
echo "✅ System started!"
echo "========================================"
echo ""
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "Your browser should open automatically."
echo "If not, visit http://localhost:3000"
echo ""
