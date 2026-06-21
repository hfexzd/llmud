.PHONY: test run docker-build docker-up reset clean

# Run all tests
test:
	PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest -v

# Run tests with short traceback
test-quick:
	PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m pytest --tb=short -q

# Start the game server locally
run:
	PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python main.py

# Build Docker image
docker-build:
	docker compose build

# Start with Docker
docker-up:
	docker compose up -d

# Stop Docker
docker-down:
	docker compose down

# Reset game state (clears DB)
reset:
	rm -f llmud.db && echo "Database cleared"

# Clean up cache files
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete
	rm -rf .pytest_cache
