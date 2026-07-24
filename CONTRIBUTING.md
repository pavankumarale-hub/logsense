# Contributing to LogSense

LogSense is a portfolio project — the primary goal is to demonstrate
production-quality patterns for AI agent tooling and observability pipelines.
That said, issues and pull requests are genuinely welcome.

## What's welcome

- **Bug reports** — if something doesn't work as documented, please open an issue
- **Correctness fixes** — wrong behaviour in the parser, clustering, or scoring logic
- **Docs improvements** — typos, broken links, unclear explanations
- **Test coverage** — additional unit or integration tests for edge cases

## What's out of scope

- New features or architecture changes without prior discussion — open an issue first
- Changes to the ADRs (those document historical decisions, not living guidelines)

## How to contribute

```bash
git clone https://github.com/pavankumarale-hub/logsense
cd logsense
make install          # creates .venv and installs dependencies
cp .env.example .env  # fill in ANTHROPIC_API_KEY
make test             # all 42 tests should pass
```

Please make sure `make test` and `make lint` both pass before opening a PR.

## Code style

- Python 3.11+, formatted with `ruff format`, linted with `ruff check`
- No comments that describe *what* code does — only *why* (non-obvious constraints,
  invariants, workarounds)
- Async throughout the storage and API layers (`aiosqlite`, `asyncio`)

## License

By contributing, you agree that your contributions will be licensed under the
same [MIT License](LICENSE) as the rest of the project.
