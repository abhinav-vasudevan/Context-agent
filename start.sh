#!/bin/bash

echo "Starting Context Agent..."

# Start FastAPI Backend in background
echo "Starting FastAPI Backend..."
python3.11 main.py &
BACKEND_PID=$!

# Start React Frontend in background
echo "Starting React Frontend..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo "Both servers started!"
echo "Backend: http://127.0.0.1:8088"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop both servers."

# Wait for Ctrl+C to kill both
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
