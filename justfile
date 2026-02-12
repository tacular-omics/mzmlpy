default: lint format check test

# Install dependencies
install:
    uv sync

# Run linting checks
lint:
    uv run ruff check src

# Format code
format:
	uv run ruff check --select I --fix src tests
	uv run ruff format src tests

# Run ty type checker
ty:
    uv run ty check src

# Run type checking
check:
    just lint
    just ty
    just test

# Run tests
test:
    uv run pytest tests

upgrade:
    @echo "Upgrading Python syntax to 3.12+..."
    @find src tests -name "*.py" -type f -exec uv run --python-preference managed pyupgrade --py312-plus {} +
    @echo "Python syntax upgraded to 3.12+"