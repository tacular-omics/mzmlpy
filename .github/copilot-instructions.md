# Copilot instructions

The canonical guide for this repo is [`CLAUDE.md`](../CLAUDE.md) (commands, architecture,
conventions, gotchas). Library usage reference: [`llms-full.txt`](../llms-full.txt).

Key rules:

1. Use `just` recipes (`just check` = lint + ty + test); fall back to `uv run`. Never install
   with pip, npm or other package managers, and never call `python`/`pytest` directly.
2. Runtime dependency is `numpy` only. Optional codecs (`pynumpress`, `zstd`, `rapidgzip`) and the
   MCP SDK are imported lazily; the base install must work without them.
3. Never hardcode CV accession strings: add them as `StrEnum` members in `src/mzmlpy/constants.py`.
4. Type everything (`X | None`, `Literal[...]` for known-set values); `just ty` must pass. Google-style docstrings.
5. No spectrum processing, peak picking or plotting here: that belongs in spxtacular.
