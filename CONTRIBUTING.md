# Contributing to mzmlpy

Bug reports, fixes and new features are welcome. Use the
[issue tracker](https://github.com/tacular-omics/mzmlpy/issues) for bugs and
questions, with a minimal example and the mzmlpy and Python versions. Report
security problems privately as described in [SECURITY.md](SECURITY.md).

## Development setup

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and
[just](https://just.systems/).

```bash
git clone https://github.com/tacular-omics/mzmlpy.git
cd mzmlpy
just install
```

`just --list` shows the other recipes.

`just install` is `uv sync --locked`, which also installs the `dev` dependency group, and
for mzmlpy that group names all four optional extras (`mcp`, `numpress`, `zstd`,
`rapidgzip`). It is therefore enough for the whole test suite on its own: 789 tests
collected, the same total as `uv sync --locked --all-extras`.

Keep the dev group. `uv sync --locked --no-dev --group test` gets pytest but none of the
extras, and the suite then reports 767 collected, 675 passed, 95 skipped and 1 failed,
against 789 collected, 781 passed and 8 skipped for the command above. The 22 missing
tests are never generated, in `test_indexed_gzip.py`, `test_mcp_protocol.py`,
`test_mcp_vocabulary.py` and `test_decoder_edge.py`, so no skip count reveals them; the
one failure is the `gzip_mode="indexed"` example in `docs/getting-started.md`, which
needs `rapidgzip`. That partial install is the one to watch for, because it still looks
like a passing suite from the skip counts alone. `--only-group test` is not the same
thing and is not quiet: it leaves out the project and `numpy` too, so collection stops
with 42 errors.

Install the commit hooks once per clone with `uvx pre-commit install`. On every
commit they run `ruff check`, `ruff format --check` and a few file checks
(`uvx pre-commit run --all-files` runs them on everything). Type checks and
tests are not in the hooks; run `just check` for those.

## Running checks

CI runs these on every pull request. Run them before you push:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check src
uv run pytest tests
python scripts/release_version.py check
```

`pytest tests` skips tests marked `slow` (subprocess launches, memory checks). CI runs them;
to run them locally too, use `uv run pytest tests --run-slow` (or `just test-all`, which also
uses the thorough Hypothesis profile).

If you change the documentation, build it the way CI does:

```bash
uv run mkdocs build --strict
```

## Pull requests

- Branch from `main` and keep each pull request to one change.
- Add tests for new behaviour and fixed bugs.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for user-visible changes.
- Do not change the version number; the maintainers set it when releasing.
- CI must pass: lint, type check, tests on Python 3.12 to 3.14, and the wheel build.

## CLAUDE.md and AI agents

`CLAUDE.md` is the maintained developer guide: commands, architecture,
conventions and known gotchas. `AGENTS.md` points other coding agents to it.
Read it before a larger change, and update it in the same pull request when your
change makes part of it wrong. AI-assisted contributions are welcome; you are
responsible for reviewing and testing what you submit.
