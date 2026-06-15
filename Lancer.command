#!/bin/bash
cd "$(dirname "$0")"
pip3 install -q pandas openpyxl openai fastapi uvicorn python-multipart
sleep 1
open http://localhost:8000
uvicorn app:app --host 0.0.0.0 --port 8000
