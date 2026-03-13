# Contributing to Banking Client Sector Intelligence

We welcome contributions from the community.

## Getting Started

1. Fork the repository and clone it locally
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Install dev dependencies: `make dev-install`
4. Make your changes and add tests
5. Run the test suite: `make test`
6. Lint your code: `make lint`
7. Submit a pull request against `main`

## Code Style

- Follow PEP 8; use `black` for formatting and `isort` for imports
- Add type hints to all public functions
- Write docstrings for public classes and methods
- Max line length: 100 characters

## Testing

- All new features must include unit tests
- Maintain test coverage above 80 %
- Use async fixtures defined in `conftest.py`

## Commit Messages

Use the conventional commit format:
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — test additions or changes
- `refactor:` — code refactoring without behaviour change
