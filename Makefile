.PHONY: dev backend frontend install build docker clean

# Run backend (5001) and frontend (5173) together. Ctrl+C stops both.
dev:
	@echo "Backend  -> http://localhost:5001"
	@echo "Frontend -> http://localhost:5173"
	@trap 'kill 0' INT TERM EXIT; \
	uv run uvicorn api.server:app --reload --port 5001 & \
	( cd frontend && pnpm run dev ) & \
	wait

# Backend only
backend:
	uv run uvicorn api.server:app --reload --port 5001

# Frontend only
frontend:
	cd frontend && pnpm run dev

# Install all dependencies
install:
	uv sync
	cd frontend && pnpm install

# Production build of the frontend
build:
	cd frontend && pnpm run build

# Run the whole stack in Docker (frontend :8080, backend :5001)
docker:
	docker compose up --build

# Remove generated artifacts
clean:
	rm -rf frontend/dist chroma_* profiles/*/output/videos/*.mp4
