#!/bin/sh
set -e
cd "$(dirname "$0")"
alembic upgrade head
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
