# Contributing to a2a-orchestrator

## Development setup

```bash
git clone https://github.com/Korrnals/a2a-orchestrator.git
cd a2a-orchestrator
pip install -e ".[dev]"
```

## Running tests

```bash
# Lint
ruff check a2a_orchestrator/ tests/

# Type check
mypy a2a_orchestrator/ --ignore-missing-imports

# All tests
pytest tests/ -v

# E2E only
pytest tests/e2e/ -v
```

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(server): add load_context tool
fix(routing): handle edge case in loop detection
docs(readme): add configuration reference
```

## Pull requests

- Branch from `main`, name as `feat/...`, `fix/...`, `docs/...`.
- All checks must pass: `ruff`, `mypy`, `pytest`.
- At least one approving review required.

## Architecture

See `docs/architecture.md` and the A2A protocol spec for the 4-layer model
and routing rules R1–R5.
