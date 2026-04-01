from unittest.mock import patch, MagicMock
import pytest
from src.core.token_budget import TokenBudget
import src.core.token_budget as tb_module


def test_estimate_basic():
    count = TokenBudget.estimate("hello world")
    assert count > 0


def test_estimate_empty():
    assert TokenBudget.estimate("") == 0


def test_budget_initial_state():
    budget = TokenBudget(total=1000)
    assert budget.total == 1000
    assert budget.used == 0
    assert budget.available == 1000
    assert not budget.is_exhausted


def test_consume_within_budget():
    budget = TokenBudget(total=1000)
    result = budget.consume(400)
    assert result is True
    assert budget.used == 400
    assert budget.available == 600


def test_consume_exceeds_budget():
    budget = TokenBudget(total=100)
    result = budget.consume(200)
    assert result is False
    assert budget.used == 0


def test_consume_exact_budget():
    budget = TokenBudget(total=100)
    result = budget.consume(100)
    assert result is True
    assert budget.is_exhausted
    assert budget.available == 0


def test_release():
    budget = TokenBudget(total=1000)
    budget.consume(300)
    budget.release(100)
    assert budget.used == 200
    assert budget.available == 800


def test_release_below_zero():
    budget = TokenBudget(total=1000)
    budget.consume(50)
    budget.release(200)
    assert budget.used == 0


def test_reset():
    budget = TokenBudget(total=1000)
    budget.consume(500)
    budget.reset()
    assert budget.used == 0
    assert budget.available == 1000


def test_count_method():
    budget = TokenBudget(total=1000)
    count = budget.count("hello world")
    assert count == TokenBudget.estimate("hello world")


def test_estimate_caches_encoding():
    """tiktoken.get_encoding should be called at most once per encoding name."""
    tb_module._ENCODING_CACHE.clear()
    fake_enc = MagicMock()
    fake_enc.encode.return_value = [1, 2, 3]
    with patch.object(tb_module.tiktoken, "get_encoding", return_value=fake_enc) as mock_get:
        TokenBudget.estimate("first call")
        TokenBudget.estimate("second call")
        TokenBudget.estimate("third call")
        mock_get.assert_called_once()
    tb_module._ENCODING_CACHE.clear()
