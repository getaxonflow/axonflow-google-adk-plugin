# Contributing

We welcome contributions to the AxonFlow Google ADK Plugin.

## Developer Certificate of Origin (DCO)

All commits must be signed off with the DCO:

```bash
git commit -s -m "your message"
```

If you have existing unsigned commits, rebase them:

```bash
git rebase --signoff origin/main
```

## Development Setup

```bash
git clone https://github.com/getaxonflow/axonflow-google-adk-plugin.git
cd axonflow-google-adk-plugin
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

## Pull Request Guidelines

- Keep PRs focused on a single change
- Update CHANGELOG.md under `[Unreleased]` for user-visible changes
- Include tests for new functionality
- All CI checks must pass before merge
