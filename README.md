---
title: Mistral OCR Showcase
emoji: 📄
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# Mistral OCR Showcase

Hugging Face Space: https://huggingface.co/spaces/snovaisg/mistral-ocr-showcase

## Overview

A Streamlit application that demonstrates Mistral's OCR model (`mistral-ocr-latest`). Users supply their own API keys, drop in a PDF (or paste a URL), run OCR to get structured markdown output with embedded images, and then chat about the extracted content using GPT-4o.

---

## Features

### Sidebar (left panel)
- **Mistral API Key** — password input, used for OCR processing
- **OpenAI API Key** — password input, used for the chat section
- **Document input** — toggle between two modes:
  - **Upload PDF** — drag-and-drop area or click-to-browse file uploader
  - **Enter URL** — paste a direct link to any publicly accessible PDF

### Main area (center / right)
- **Apply Mistral OCR** button — runs `mistral-ocr-latest` against the selected document; disabled until both a Mistral key and a document source are provided
- **OCR Results** — rendered markdown output with images embedded inline as base64 data URLs (auto-detected MIME type: JPEG, PNG, GIF)
- **Raw markdown expander** — collapsed by default; shows the raw markdown string for inspection or copying
- **Chat about this document** — powered by `gpt-4o`:
  - Full OCR markdown is sent as system context on every request
  - Multi-turn conversation (history is kept in session state)
  - **Clear chat** button resets the thread without re-running OCR
  - Submitting a new question with a fresh context after clearing keeps the UI uncluttered

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit 1.54.0 |
| OCR | Mistral `mistral-ocr-latest` via `mistralai` 1.12.2 |
| Chat | OpenAI `gpt-4o` via `openai` 2.21.0 |
| Deployment target | Hugging Face Spaces (Streamlit SDK) |

---

## Running locally

This project uses [uv](https://docs.astral.sh/uv/) for environment management.

### Prerequisites

Install `uv` if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### First-time setup

Clone/navigate to the project directory, then let `uv` create the virtual environment and install all dependencies from the lockfile:

```bash
cd ideas/mistral-ocr-showcase
uv sync
```

That's it — `uv` reads `pyproject.toml` and `uv.lock` and installs the exact pinned versions into `.venv/`.

### Run the app

```bash
uv run streamlit run app.py
```

Streamlit will open `http://localhost:8501` in your browser automatically.

### Adding or updating dependencies

```bash
uv add <package>        # add a new dependency
uv remove <package>     # remove a dependency
uv lock --upgrade       # refresh the lockfile to latest compatible versions
```

---

## Deploying to Hugging Face Spaces

1. Create a new Space with the **Streamlit** SDK.
2. Upload `app.py` and `requirements.txt` to the Space repository.
3. The Space will install dependencies and launch automatically — no secrets need to be pre-configured, as users supply their own API keys at runtime.

### Auto-sync from GitHub (already configured in this repo)

This repo includes a workflow at `.github/workflows/sync-to-hf-space.yml` that deploys every push to `main` into:

- `snovaisg/mistral-ocr-showcase`

To enable it, add this repository secret in GitHub:

- `HF_TOKEN`: a Hugging Face User Access Token with write access to the Space.

---

## Status

Registered on 2026-02-17
Last updated on 2026-02-17
