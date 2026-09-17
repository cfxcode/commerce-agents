"""Live usage accounting remains fail-closed without model requests."""

import pytest


@pytest.mark.parametrize(
    "raw_usage",
    [
        None,
        {},
        {"input_tokens": 1},
        {"input_tokens": -1, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": True},
        {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": -2},
    ],
)
def test_live_missing_or_invalid_usage_blocks_further_paid_calls(raw_usage):
    from types import SimpleNamespace

    from commerce_reasoning.live_acceptance import ModelBudget, ModelBudgetExceeded

    budget = ModelBudget()
    budget.record(
        SimpleNamespace(usage=SimpleNamespace(**raw_usage) if raw_usage is not None else None)
    )
    assert budget.unmetered_calls == 1 and budget.tokens == 0
    with pytest.raises(ModelBudgetExceeded):
        budget.reserve({"max_tokens": 10})
