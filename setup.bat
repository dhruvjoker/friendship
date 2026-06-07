@echo off
REM Setup script for Friendship Circle on Windows

echo.
echo ============================================
echo  Friendship Circle Setup
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/5] Checking Python version...
python --version

echo.
echo [2/5] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Error creating virtual environment
    pause
    exit /b 1
)

echo.
echo [3/5] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo [4/5] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error installing dependencies
    pause
    exit /b 1
)

echo.
echo [5/5] Creating .env file...
if not exist .env (
    copy .env.example .env
    echo .env file created. Please update it with your settings.
) else (
    echo .env file already exists
)

echo.
echo ============================================
echo  Setup Complete!
echo ============================================
echo.
echo To start the development server, run:
echo   venv\Scripts\activate.bat
echo   python run.py
echo.
echo Then open your browser and go to:
echo   http://localhost:5000
echo.
pause
