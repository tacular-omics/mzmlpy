default: check

# Install dependencies
install:
    uv sync --locked

# Run linting checks
lint:
    uv run ruff check src tests

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
test *args:
    uv run pytest tests {{args}}

upgrade:
    @echo "Upgrading Python syntax to 3.12+..."
    @find src tests -name "*.py" -type f -exec uv run --python-preference managed pyupgrade --py312-plus {} +
    @echo "Python syntax upgraded to 3.12+"


# Run tests with coverage
test-cov:
    uv run pytest tests --cov=src/mzmlpy --cov-branch --cov-report=term-missing --cov-report=html --cov-report=xml --junitxml=junit.xml -o junit_family=legacy

codecov-tests: test-cov

docs:  # Build and serve docs (port 8001)
    uv run mkdocs serve --dev-addr=localhost:8001

docs-build:  # Build docs to site/
    uv run mkdocs build --strict
