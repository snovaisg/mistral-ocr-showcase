from mistralai import Mistral
from openai import OpenAI


def run_ocr(api_key: str, pdf_bytes: bytes | None = None, url: str | None = None):
    """Call Mistral OCR and return the raw response."""
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
    client = OpenAI(api_key=api_key)

    system_msg = (
        "You are a clinical document extraction assistant focused on lab reports. "
        "Extract and explain information only from the OCR content below. "
        "When relevant, provide structured tables with: test name, value, unit, "
        "reference range, and abnormality flag. If data is missing, say so clearly.\n\n"
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
