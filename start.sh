#!/bin/bash
# 修仙 MUD — llmud
# Quick start script for development

set -e

# Check for .env
if [ ! -f .env ]; then
    echo "No .env found. Creating from .env.example..."
    cp .env.example .env
    echo "Please edit .env and set your DEEPSEEK_API_KEY"
    exit 1
fi

# Load env
export $(grep -v '^#' .env | xargs)

echo "========================================="
echo "  修仙 MUD — llmud"
echo "  Starting server at http://localhost:8001"
echo "========================================="

PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python main.py
