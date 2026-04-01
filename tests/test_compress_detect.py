"""Tests for src.core.compress_detect — shared compress-hint detection."""
import pytest

from src.core.compress_detect import detect_compress_hint


class TestDetectCompressHint:
    def test_code_hint(self):
        text = "def foo():\n    pass\ndef bar():\n    pass\nclass Baz:\n    pass"
        assert detect_compress_hint(text) == "code_compact"

    def test_code_with_backticks(self):
        text = "```python\ncode\n```\n```js\nmore\n```\n```bash\necho hi\n```"
        assert detect_compress_hint(text) == "code_compact"

    def test_bullet_hint(self):
        text = "- step one\n- step two\n- step three\n- step four"
        assert detect_compress_hint(text) == "mermaid"

    def test_numbered_steps_hint(self):
        text = "1. First step\n2. Second step\n3. Third step"
        assert detect_compress_hint(text) == "mermaid"

    def test_yaml_struct_hint(self):
        text = "name: foo\nversion: 1.0\nauthor: bar\ndescription: baz"
        assert detect_compress_hint(text) == "yaml_struct"

    def test_kv_with_equals(self):
        text = "HOST = localhost\nPORT = 8080\nDEBUG = true\nLOG = verbose"
        assert detect_compress_hint(text) == "yaml_struct"

    def test_table_long_prose(self):
        text = "a" * 201
        assert detect_compress_hint(text) == "bullet_extract"

    def test_none_for_short_text(self):
        assert detect_compress_hint("short") is None

    def test_none_for_empty(self):
        assert detect_compress_hint("") is None

    def test_code_takes_priority_over_steps(self):
        text = "def a():\ndef b():\ndef c():\n- one\n- two\n- three"
        assert detect_compress_hint(text) == "code_compact"

    def test_steps_take_priority_over_kv(self):
        text = "- one\n- two\n- three\nfoo: bar\nbaz: qux\nkey: val"
        assert detect_compress_hint(text) == "mermaid"

    def test_mermaid_with_headings(self):
        text = "# Heading 1\n## Heading 2\n### Heading 3"
        assert detect_compress_hint(text) == "mermaid"

    def test_exactly_200_chars_no_bullet(self):
        text = "x" * 200
        assert detect_compress_hint(text) is None

    def test_201_chars_returns_bullet(self):
        text = "x" * 201
        assert detect_compress_hint(text) == "bullet_extract"
