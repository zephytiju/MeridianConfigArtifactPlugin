# Contributing

This repository contains exactly one Python distribution. Changes must preserve the public
Configuration and Artifact profiles, consume only Meridian's structured and object Catalogs,
and remain provider-neutral.

Create a virtual environment with Python 3.12–3.14, then run:

```console
python -m pip install -e '.[test]'
ruff format --check src tests scripts
ruff check src tests scripts
mypy src
python scripts/verify_contracts.py
pytest
bandit -r src -c pyproject.toml
```

Pull requests must include tests and contract updates for public behavior changes. Architecture
or interface changes require an approved design write-back before implementation.
