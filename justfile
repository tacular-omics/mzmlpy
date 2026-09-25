default: check

# Install locked dependencies
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

# Run lint, ty and tests (the default recipe; does not format)
check:
    just lint
    just ty
    just test

# Run tests (fast default: skips tests marked slow)
test *args:
    uv run pytest tests {{args}}

# Run every test, including slow ones, with the thorough Hypothesis profile (what CI covers)
test-all *args:
    RUN_SLOW=1 HYPOTHESIS_PROFILE=thorough uv run pytest tests {{args}}

# Rewrite src and tests to Python 3.12+ syntax with pyupgrade
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

# --- release (standard tacular-omics recipes; canonical copy in the workspace templates/) ---

# Set the version everywhere and date the [Unreleased] changelog section
set-version version:
    python scripts/release_version.py sync --set {{version}}

# Copy __version__ to CITATION.cff after editing it by hand
sync-version:
    python scripts/release_version.py sync

# Fail if version metadata disagrees
check-version:
    python scripts/release_version.py check
