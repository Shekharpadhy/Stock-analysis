.PHONY: install dev-install run test lint format migrate docker-up docker-down

install:
	pip install -r requirements.txt

dev-install: install
	pip install -r requirements-dev.txt

run:
	uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest tests/ -v --cov=backend --cov-report=term-missing

lint:
	flake8 backend/ --max-line-length=100
	mypy backend/ --ignore-missing-imports

format:
	black backend/ tests/
	isort backend/ tests/

migrate:
	alembic upgrade head

docker-up:
	docker-compose up -d --build

docker-down:
	docker-compose down -v
