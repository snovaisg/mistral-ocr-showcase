---
title: Lab Results Extractor
emoji: 🧪
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Lab Results Extractor

Hugging Face Space: https://huggingface.co/spaces/snovaisg/mistral-ocr-showcase

## Overview

This project is a Streamlit app for extracting and reviewing lab report data:
- OCR extraction from PDF lab reports using Mistral (`mistral-ocr-latest`)
- Follow-up structured analysis via OpenAI (`gpt-4o`)
- Batch extraction from ZIP files containing multiple PDFs
- Side-by-side UX for extraction output and guided prompts

Users provide their own API keys at runtime.

## Project Structure

- `app.py`: Streamlit UI, state management, rendering, interaction flow
- `ocr_chat_api.py`: isolated API methods for Mistral OCR and OpenAI chat calls
- `requirements.txt`: pinned runtime dependencies
- `Dockerfile`: container runtime used by Hugging Face Space

## Features

- PDF upload or public PDF URL input
- ZIP upload for multi-document extraction
- OCR markdown rendering with embedded inline images
- Raw OCR markdown inspector
- Lab-focused chat prompts for:
  - biomarker tables
  - abnormal/out-of-range value detection
  - follow-up discussion prep
- Field-based batch extraction where missing fields are returned as `not found in document`

## Run Locally

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start app:

```bash
streamlit run app.py
```

3. Open:

```text
http://localhost:8501
```

## Deploying to Hugging Face Spaces (Docker)

This repo is configured for Docker-based deployment on HF Spaces.

- App listens on port `7860`
- Streamlit is started with:
  - `--server.address=0.0.0.0`
  - `--server.enableCORS=false`
  - `--server.enableXsrfProtection=false`

These flags are set for proxy compatibility in HF Spaces and to avoid upload-related 403 errors.

## GitHub Action Deployment

Deployments are triggered from `main` via:
- `.github/workflows/sync-to-hf-space.yml`

Required secret:
- `HF_TOKEN`: Hugging Face token with write access to the target Space

## Dependencies

- `streamlit==1.54.0`
- `mistralai==1.12.2`
- `openai==2.21.0`
