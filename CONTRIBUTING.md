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

`just install` is `uv sync --locked`, which also installs the `dev` dependency group.
mzmlpy has four optional extras, `mcp`, `numpress`, `zstd` and `rapidgzip`, and the `dev`
group names every one of them, so that one command is enough for the whole test suite.
`uv pip list` is the check worth running: with `mcp`, `pynumpress`, `zstd` and
`rapidgzip` all present, no test is skipped for want of an extra.

Read the passed and skipped counts, not the collected total. A missing extra usually
skips a test that was already collected, so the collected total is the same either way
and only the pass count moves; other tests are never parametrized into existence, in
`test_indexed_gzip.py`, `test_mcp_protocol.py`, `test_mcp_vocabulary.py` and
`test_decoder_edge.py`, so those leave the total without ever appearing as a skip.

Keep the dev group. `uv sync --locked --no-dev --group test` gets pytest but none of the
extras, and for mzmlpy that is only partly quiet: the skip count rises sharply, the tests
above drop out of collection, and the `gzip_mode="indexed"` example in
`docs/getting-started.md` fails outright for want of `rapidgzip`. `--only-group test` is
not the same thing and is louder still: it leaves out the project and `numpy` as well, so
collection stops with errors.

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
