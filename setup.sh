#!/bin/bash

echo "================================================"
echo "  Setting up Context-agent test environment...  "
echo "================================================"

echo ""
echo "[1/3] Creating Python virtual environment (venv)..."
python3 -m venv venv

echo ""
echo "[2/3] Activating venv and installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ -d "frontend" ]; then
    echo ""
    echo "[3/3] Installing frontend dependencies (node_modules)..."
    cd frontend
    npm install
    cd ..
else
    echo ""
    echo "[3/3] Frontend directory not found, skipping npm install."
fi

echo ""
echo "================================================"
echo "  Setup Complete! "
echo "  The 'venv' folder has been created and populated."
echo "  You can now inject this codebase into your agent"
echo "  to test if it correctly detects the existing venv."
echo "================================================"
