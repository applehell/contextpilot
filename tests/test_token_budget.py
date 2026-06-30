from unittest.mock import patch, MagicMock
from src.core.token_budget import TokenBudget
import src.core.token_budget as tb_module


def test_estimate_basic():
    count = TokenBudget.estimate("hello world")
    assert count > 0


def test_estimate_empty():
    assert TokenBudget.estimate("") == 0


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
