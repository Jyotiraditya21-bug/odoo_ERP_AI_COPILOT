.PHONY: up down logs test lint evaluate

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f odoo ai-service

test:
	python -m pytest ai_service/tests -q

lint:
	python -m ruff check ai_service/app ai_service/tests evaluation

evaluate:
	python evaluation/run_evaluation.py

