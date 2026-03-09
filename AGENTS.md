# AGENTS.md

## Repository Setup

- This repository pushes code to GitHub (`origin`).
- A GitHub Action (`.github/workflows/sync-to-hf-space.yml`) syncs updates to the Hugging Face Space after pushes to `main`.
- Primary deployment flow: push to GitHub; let the action update the HF Space repo.

## Local Testing Before Push

- Use local Docker to validate the same container runtime used in Hugging Face Spaces before each push.
- Recommended check sequence:
  1. Rebuild image after code changes:
```bash
docker build -t lab-results-extractor:local .
```
  2. Run container for local test:
```bash
docker run --rm -p 7860:7860 --name lab-results-extractor lab-results-extractor:local
```
  3. Open app:
     - `http://localhost:7860`
  4. Verify critical behavior:
     - PDF upload works
     - OCR extraction runs with your Mistral key
     - Chat follow-up works with your OpenAI key
  5. Stop test run:
     - `Ctrl+C` in the container terminal (or `docker stop lab-results-extractor` from another terminal)
- Push to `main` only after Docker local checks pass.

## Quick Rebuild + Test

```bash
docker build -t lab-results-extractor:local . && docker run --rm -p 7860:7860 --name lab-results-extractor lab-results-extractor:local
```
