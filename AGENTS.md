# AGENTS.md

## Repository Setup

- This repository pushes code to GitHub (`origin`).
- A GitHub Action (`.github/workflows/sync-to-hf-space.yml`) syncs updates to the Hugging Face Space after pushes to `main`.
- Primary deployment flow: push to GitHub; let the action update the HF Space repo.

## Local Testing Before Push

- Use the local `uv` environment before each push.
- Recommended check sequence:
  1. `uv sync`
  2. `uv run streamlit run app.py`
- Verify upload + OCR + chat behavior locally before pushing to `main`.
