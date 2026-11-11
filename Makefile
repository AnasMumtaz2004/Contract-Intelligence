.PHONY: env up down logs demo demo-quick test lint clean

# Create .env with a fresh secret key (you still add your GROQ_API_KEY)
env:
	@test -f .env || (cp .env.example .env && sed -i.bak "s/^SECRET_KEY=.*/SECRET_KEY=$$(openssl rand -hex 32)/" .env && rm -f .env.bak && echo "Created .env. Add your GROQ_API_KEY to it.")

# Build and start everything. The first build takes several minutes.
up: env
	docker compose up --build -d
	@echo "App: http://localhost:5173   API docs: http://localhost:8000/docs"

down:
	docker compose down

logs:
	docker compose logs -f backend

# Load the sample contracts (about 10 minutes). Login: demo@example.com / demo-password-123
demo:
	docker compose exec backend python -m scripts.seed_sample_data --email demo@example.com --password demo-password-123

# A smaller demo: 4 contracts with their amendments (a few minutes)
demo-quick:
	docker compose exec backend python -m scripts.seed_sample_data --email demo@example.com --password demo-password-123 --quick

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run --with ruff ruff check --config ../ruff.toml . ../eval

# Stop everything and delete all data
clean:
	docker compose down -v