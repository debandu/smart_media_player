# Contributing to Smart Media Player

Thanks for your interest in contributing! Please read this before you start.

---

## Platform

This project runs on **macOS, Windows, and Linux** — the player is built on PySide6/Qt6, which
is cross-platform, and `MediaPlayerFactory` selects the right class for the OS you're on. CI
runs the suite on Linux and Windows runners on every PR; macOS is covered by local development.

If you're adding a genuinely OS-specific behaviour (native taskbar integration, desktop-file
association, etc.), it belongs as an override on the relevant `*MediaPlayer` subclass — see
`ARCHITECTURE.md` §6 for the pattern.

---

## Step 1 — Fork and clone

Do **not** clone this repo directly. Fork it first:

1. Click **Fork** on the top right of this page
2. Clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/smart-media-player.git
cd smart-media-player
```

---

## Step 2 — Set up your environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes everything in `requirements.txt` plus the test
tooling, so it is the only file you need to install. Check your setup works:

```bash
python -m pytest tests/ -v
```

All tests should pass. They need no display, no GPU, no API key, and no network
— every external call is mocked and Qt runs headless.

Create a `.env` file in the project root (never commit this file):

```env
GROQ_API_KEY=your_groq_api_key_here
MODEL=llama3-8b-8192
BASE_URL=https://api.groq.com/openai/v1
CHROMA_DB_PATH=./chroma_db
```

Get a free Groq API key at [console.groq.com](https://console.groq.com).

---

## Step 3 — Create a branch

Never work directly on `main`. Create a branch named after what you're doing:

| Type | Example |
|---|---|
| New feature | `feature/add-subtitle-display` |
| Bug fix | `fix/seek-bar-click` |
| Docs | `docs/update-readme` |
| Refactor | `refactor/rag-split-classes` |

```bash
git checkout -b feature/your-feature-name
```

---

## Step 4 — Make your changes

- Follow the existing code style
- Do not hardcode API keys or file paths
- Do not commit your `.env`, `chroma_db/`, or any video files
- Keep changes focused — one feature or fix per PR

### Tests

Every change needs test movement:

| Your change | What's expected |
|---|---|
| New function or method | Tests for the happy path, edge cases, and failure mode |
| Bug fix | A regression test — verify it **fails** before your fix and passes after |
| Behaviour change | Update the existing assertions; don't delete the test |
| Pure refactor | Existing tests must pass **unmodified** |

Run the full suite before you push:

```bash
python -m pytest tests/ -v
```

Two rules worth knowing:

- **Never assert against a copy of the code under test.** If something seems
  untestable, find a way to reach the real object — re-implementing it in the
  test file silently loses all coverage.
- **A passing test is not proof of coverage.** For a regression test, break the
  fix and confirm the test actually fails.

CI runs the same suite on every PR (Python 3.10 and 3.13), so a failure here
blocks the merge.

---

## Step 5 — Open a Pull Request

Push your branch to your fork:

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request against the `main` branch of this repo. Fill in the PR template fully — PRs with no description will not be reviewed.

---

## What happens next

- Your PR will be reviewed by the maintainer
- You may be asked to make changes before it is merged
- Once approved it will be squash-merged into `main`

---

## Reporting bugs

Open an issue with:
- What you did
- What you expected to happen
- What actually happened
- Your OS (and version) and Python version
