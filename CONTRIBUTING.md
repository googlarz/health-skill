# Contributing

Thanks for your interest in Health Skill.

## Getting started

```bash
git clone https://github.com/googlarz/health-skill.git
cd health-skill
python3 -m unittest tests.test_care_workspace -v
```

All tests should pass with no external dependencies. PDF and OCR features require optional packages (see `pyproject.toml`).

## Running checks

```bash
# Tests
python3 -m unittest tests.test_care_workspace -v

# Type checking (optional)
pip install mypy
mypy scripts/ --ignore-missing-imports
```

## Pull requests

- Keep changes focused — one concern per PR.
- Add or update tests for new behavior.
- Run the test suite before submitting.
- Follow existing code patterns (atomic writes, trust-aware extraction, review tiers).

## What kinds of contributions are useful

- Bug fixes with a failing test.
- New extraction patterns (lab formats, medication patterns).
- Better OCR handling for scanned documents.
- Improved rendering views.
- Documentation improvements.

## What this project is not

This is a local-first Claude skill, not a regulated healthcare platform. Contributions should respect the safety model in `SKILL.md` and `references/safety-protocol.md`.
