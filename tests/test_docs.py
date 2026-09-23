import shutil
from pathlib import Path

import pytest
from pytest_examples import CodeExample, EvalExample, find_examples

ROOT = Path(__file__).parent.parent


@pytest.fixture
def docs_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run examples against a copy of tests/data so index sidecars never land in the repo."""
    data = tmp_path / "tests" / "data"
    data.mkdir(parents=True)
    for name in ("example.mzML", "example.mzML.gz"):
        shutil.copy2(ROOT / "tests" / "data" / name, data / name)
    monkeypatch.chdir(tmp_path)
    return data


@pytest.mark.parametrize("example", list(find_examples(ROOT / "docs" / "getting-started.md")), ids=str)
def test_getting_started(example: CodeExample, eval_example: EvalExample, docs_cwd: Path):
    eval_example.run(example)
