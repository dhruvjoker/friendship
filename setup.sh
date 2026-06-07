#!/bin/bash

# Setup script for Friendship Circle on Linux/Mac

echo ""
echo "============================================"
echo "  Friendship Circle Setup"
echo "============================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8+ first"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-venv python3-pip"
    echo "  macOS: brew install python3"
    exit 1
fi

echo "[1/5] Checking Python version..."
python3 --version

echo ""
echo "[2/5] Creating virtual environment..."
python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "Error creating virtual environment"
    exit 1
fi

echo ""
echo "[3/5] Activating virtual environment..."
source venv/bin/activate

echo ""
echo "[4/5] Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error installing dependencies"
    exit 1
fi

echo ""
echo "[5/5] Creating .env file..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ".env file created. Please update it with your settings."
else
    echo ".env file already exists"
fi

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "To start the development server, run:"
echo "  source venv/bin/activate"
echo "  python run.py"
echo ""
echo "Then open your browser and go to:"
echo "  http://localhost:5000"
echo ""
