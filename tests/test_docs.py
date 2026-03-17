import pytest
from pytest_examples import CodeExample, EvalExample, find_examples


@pytest.mark.parametrize("example", find_examples("docs/getting-started.md"), ids=str)
def test_getting_started(example: CodeExample, eval_example: EvalExample):
    eval_example.run(example)
