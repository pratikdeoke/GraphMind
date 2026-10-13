@echo off
setlocal
set "ROOT=%~dp0"

if /i "%~1"=="backend" goto backend
if /i "%~1"=="frontend" goto frontend

cd /d "%ROOT%"

if not exist "backend\.env" (
    echo backend\.env is missing. Copying backend\.env.example.
    copy "backend\.env.example" "backend\.env" >nul
    if errorlevel 1 (
        echo ERROR: Could not create backend\.env.
        pause
        exit /b 1
    )
    echo Review backend\.env and configure any required credentials.
)

if not exist "backend\venv\Scripts\python.exe" (
    echo ERROR: Backend virtual environment not found at backend\venv.
    echo Create it and install backend\requirements.txt before running this file.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo ERROR: Frontend dependencies not found at frontend\node_modules.
    echo Run npm install in the frontend folder before running this file.
    pause
    exit /b 1
)

docker compose up -d --wait --wait-timeout 90 postgres neo4j
if errorlevel 1 (
    echo ERROR: Could not start PostgreSQL and Neo4j. Check that Docker Desktop is running.
    pause
    exit /b 1
)

echo.
echo GraphMind is starting. Open these URLs after the services are ready:
echo   Frontend:  http://localhost:5173
echo   Backend:   http://localhost:8001
echo   API docs:  http://localhost:8001/docs
echo.
echo Keep the backend and frontend terminal windows open while using GraphMind.

start "GraphMind Backend" "%ComSpec%" /k call "%~f0" backend
start "GraphMind Frontend" "%ComSpec%" /k call "%~f0" frontend
exit /b 0

:backend
cd /d "%ROOT%backend"
set "API_HOST=0.0.0.0"
set "API_PORT=8001"
"%ROOT%backend\venv\Scripts\python.exe" -c "import api.main"
if errorlevel 1 (
    echo ERROR: Backend startup check failed. Review the Python error above.
    pause
    exit /b 1
)
"%ROOT%backend\venv\Scripts\python.exe" -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8001
pause
exit /b

:frontend
curl.exe --fail --silent --output NUL --max-time 3 http://localhost:5173
if not errorlevel 1 (
    echo Frontend is already running at http://localhost:5173. Reusing it.
    exit /b 0
)
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo ERROR: Port 5173 is already in use, but the frontend did not respond.
    echo Stop the process using port 5173, then run this launcher again.
    pause
    exit /b 1
)
cd /d "%ROOT%frontend"
set "VITE_API_URL=http://localhost:8001"
call npm.cmd run dev -- --host 0.0.0.0 --strictPort
pause
exit /b
