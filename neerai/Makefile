.PHONY: setup backend frontend test test-backend test-frontend build demo
setup:
	cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt || .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install
backend:
	cd backend && python -m uvicorn app.main:create_app --factory --reload --port 8000
frontend:
	cd frontend && npm run dev
test: test-backend test-frontend
test-backend:
	cd backend && python -m pytest
test-frontend:
	cd frontend && npm test && npm run typecheck
build:
	cd frontend && npm run build
demo:
	python scripts/demo.py
