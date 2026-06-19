@echo off
echo Starting Context Agent...

echo Starting FastAPI Backend...
start "Context Agent Backend" cmd /k "python main.py"

echo Starting React Frontend...
cd frontend
start "Context Agent Frontend" cmd /k "npm run dev"

echo Both servers started!
echo Backend: http://127.0.0.1:8088
echo Frontend: http://localhost:5173
