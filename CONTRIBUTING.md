# Contributing to Context Pilot

Thanks for your interest in contributing!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/applehell/contextpilot.git
cd contextpilot/app

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# Run the app locally
python -m src.web --port 8080 --mcp-port 8400
```

## Running Tests

```bash
# Full test suite
pytest

# With coverage
pytest --cov=src --cov-report=term-missing

# Single test file
pytest tests/test_mcp_server.py -v
```

## Project Structure

```
src/
  core/         # Block model, assembler, compressors, relevance engine
  storage/      # SQLite database, memory store, profiles, usage tracking
  connectors/   # Plugin-based connectors (Paperless, GitHub, Gitea, etc.)
  importers/    # Import from Claude, Copilot, SQLite
  interfaces/   # MCP server, CLI
  web/          # FastAPI app, templates, static assets
tests/          # pytest test suite
```

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the test suite (`pytest`)
5. Commit with a clear message
6. Open a pull request

## Code Style

- Python 3.11+, type hints on all functions
- No unnecessary docstrings or comments — code should be self-explanatory
- Tests for new features and bug fixes
- SQLite queries must use parameterized placeholders (`?`)

## Reporting Issues

Use [GitHub Issues](https://github.com/applehell/contextpilot/issues) to report bugs or request features.
