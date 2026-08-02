# Contributing to Smart Media Player

Thanks for your interest in contributing! Please read this before you start.

---

## Platform

This project currently runs on **macOS only**. Contributions that add Windows or Linux support are very welcome.

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
pip install -r requirements.txt
```

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
- Your macOS version and Python version
