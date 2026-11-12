.PHONY: install install-web build run dev schema clean docker-build docker-up docker-down docker-logs

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

install:
	python3 -m venv backend/.venv
	$(PIP) install -r backend/requirements.txt
	@test -f .env || cp .env.example .env

install-web:
	cd frontend && npm install

build:
	cd frontend && npm run build

run:
	cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8080

dev:
	./scripts/dev.sh

schema:
	$(PY) -c "import sys; sys.path.insert(0,'backend'); from pathlib import Path; from app.fntv import dump_schema; Path('docs/fntv-schema.sql').write_text(dump_schema(Path('DB/trimmedia.db')), encoding='utf-8')"

docker-build:
	docker compose -f docker-compose.build.yml build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

clean:
	rm -rf backend/.pytest_cache backend/app/__pycache__ backend/app/**/__pycache__ backend/tests/__pycache__
