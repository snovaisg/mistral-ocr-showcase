import json
import threading
import time

from mistralai import Mistral
from openai import OpenAI

_PROVIDER_COOLDOWN_SECONDS = 5.0
_last_provider_call_ts: dict[str, float] = {}
_provider_lock = threading.Lock()


def _enforce_provider_cooldown(provider: str) -> None:
    """Ensure at least 5 seconds between calls to the same provider."""
    with _provider_lock:
        now = time.monotonic()
        last = _last_provider_call_ts.get(provider)
        if last is not None:
            wait = _PROVIDER_COOLDOWN_SECONDS - (now - last)
            if wait > 0:
                time.sleep(wait)
        _last_provider_call_ts[provider] = time.monotonic()


def run_ocr(api_key: str, pdf_bytes: bytes | None = None, url: str | None = None):
    """Call Mistral OCR and return the raw response."""
    _enforce_provider_cooldown("mistral")
    client = Mistral(api_key=api_key)

    if pdf_bytes:
        upload = client.files.upload(
            file={"file_name": "document.pdf", "content": pdf_bytes},
            purpose="ocr",
        )
        signed = client.files.get_signed_url(file_id=upload.id)
        doc = {"type": "document_url", "document_url": signed.url}
    else:
        doc = {"type": "document_url", "document_url": url}

    return client.ocr.process(
        model="mistral-ocr-latest",
        document=doc,
        include_image_base64=True,
    )


def run_chat(
    api_key: str,
    markdown_content: str,
    question: str,
    history: list[tuple[str, str]],
) -> str:
    """Send a lab-report extraction question to GPT-4o with OCR markdown context."""
    _enforce_provider_cooldown("openai")
    client = OpenAI(api_key=api_key)

    system_msg = (
        "You are a clinical document extraction assistant focused on lab reports. "
        "Extract and explain information only from the OCR content below. "
        "When relevant, provide structured tables with: test name, value, unit, "
        "reference range, and abnormality flag. "
        "If requested information is not present in the document, explicitly say in Portuguese: "
        "'Nao foi possivel encontrar essa informacao no documento.' "
        "Do not invent values.\n\n"
        "--- DOCUMENT CONTENT (OCR) ---\n"
        f"{markdown_content}\n"
        "--- END OF DOCUMENT ---"
    )
    messages = [{"role": "system", "content": system_msg}]
    for q, a in history:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})

    resp = client.chat.completions.create(model="gpt-4o", messages=messages)
    return resp.choices[0].message.content


def run_document_extraction(
    api_key: str,
    markdown_content: str,
    extraction_request: str,
) -> dict:
    """Extract requested fields from one OCR document and return structured JSON."""
    _enforce_provider_cooldown("openai")
    client = OpenAI(api_key=api_key)

    system_msg = (
        "You extract data from one lab report document at a time. "
        "Only use information present in the provided OCR document. "
        "You must return valid JSON only. "
        "For every requested field, return one object with keys: "
        "field, value, evidence, status. "
        "Allowed status values: found, not_found. "
        "If the field is missing, set status to not_found and value to exactly "
        "'not found in document'. Set evidence to ''.\n\n"
        "Output JSON shape:\n"
        "{\n"
        '  "fields": [\n'
        "    {\n"
        '      "field": "string",\n'
        '      "value": "string",\n'
        '      "evidence": "string",\n'
        '      "status": "found|not_found"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "--- DOCUMENT CONTENT (OCR) ---\n"
        f"{markdown_content}\n"
        "--- END OF DOCUMENT ---"
    )

    user_msg = (
        "Requested information to extract from this document:\n"
        f"{extraction_request}"
    )

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)
