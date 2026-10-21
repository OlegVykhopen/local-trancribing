#!/bin/bash
cd "$(dirname "$0")"
export DYLD_LIBRARY_PATH=/opt/homebrew/opt/ffmpeg@7/lib
if [ ! -d frontend/dist ]; then echo "WARNING: frontend/dist missing — run: cd frontend && npm run build"; fi
if [ -z "$NO_BROWSER" ]; then (sleep 1.5 && open "http://127.0.0.1:8756") & fi
exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8756
