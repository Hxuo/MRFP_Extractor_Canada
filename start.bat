@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Virtual environment missing. Read README.md to install dependencies.
 pause
 exit /b 1
)
echo Open http://localhost:5000 in your browser
".venv\Scripts\python.exe" app.py
pause
