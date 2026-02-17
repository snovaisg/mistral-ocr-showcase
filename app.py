import re

import streamlit as st
from mistralai import Mistral
from openai import OpenAI

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Mistral OCR Showcase",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Minimal CSS tweaks ───────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        /* Make primary buttons full-width in sidebar */
        section[data-testid="stSidebar"] .stButton > button { width: 100%; }
        /* Tighten chat bubbles */
        .chat-user   { background:#e8f4fd; padding:.75rem 1rem; border-radius:8px; margin-bottom:.4rem; }
        .chat-assist { background:#f4f4f4; padding:.75rem 1rem; border-radius:8px; margin-bottom:.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── Session-state defaults ───────────────────────────────────────────────────
for _k, _v in {
    "ocr_markdown": None,
    "ocr_images": {},
    "ocr_done": False,
    "chat_history": [],
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _run_ocr(api_key: str, pdf_bytes: bytes | None = None, url: str | None = None):
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


def _combine_markdown(ocr_response) -> str:
    """Concatenate all pages' markdown with page dividers."""
    parts = []
    for i, page in enumerate(ocr_response.pages):
        if len(ocr_response.pages) > 1:
            parts.append(f"\n\n---\n*— Page {i + 1} —*\n\n")
        parts.append(page.markdown or "")
    return "".join(parts)


def _build_image_map(ocr_response) -> dict:
    """Return {image_id: base64_string} for all images in the response."""
    images: dict = {}
    for page in ocr_response.pages:
        if not hasattr(page, "images") or not page.images:
            continue
        for img in page.images:
            img_id = getattr(img, "id", None)
            b64 = getattr(img, "image_base64", None)
            if img_id and b64:
                images[img_id] = b64
    return images


def _img_tag(b64: str, alt: str = "") -> str:
    """Wrap a base64 string in an HTML <img> tag with an auto-detected MIME."""
    if b64.startswith("data:"):
        src = b64
    else:
        if b64.startswith("/9j/"):
            mime = "image/jpeg"
        elif b64.startswith("iVBOR"):
            mime = "image/png"
        elif b64.startswith("R0lGOD"):
            mime = "image/gif"
        else:
            mime = "image/jpeg"
        src = f"data:{mime};base64,{b64}"
    return f'<img src="{src}" alt="{alt}" style="max-width:100%;height:auto;margin:8px 0;" />'


def _render_markdown_with_images(markdown: str, images: dict) -> str:
    """Replace `![alt](img_id)` references with inline HTML <img> tags."""
    def _replace(match):
        alt = match.group(1)
        img_id = match.group(2)
        if img_id in images:
            return _img_tag(images[img_id], alt)
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, markdown)


def _run_chat(
    api_key: str,
    markdown_content: str,
    question: str,
    history: list[tuple[str, str]],
) -> str:
    """Send a question to GPT-4o with the OCR markdown as context."""
    client = OpenAI(api_key=api_key)

    system_msg = (
        "You are a helpful assistant that answers questions about a document that was "
        "processed with an OCR model. Base your answers solely on the document content "
        "provided below.\n\n"
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


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Mistral OCR")
    st.caption("Configure your keys, then drop in a document.")

    # API keys
    st.subheader("API Keys")
    mistral_key = st.text_input(
        "Mistral API Key",
        type="password",
        placeholder="Enter your Mistral API key…",
        help="Required for OCR. Get yours at console.mistral.ai",
    )
    openai_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="Enter your OpenAI API key…",
        help="Required for the chat section. Get yours at platform.openai.com",
    )

    st.divider()

    # Document input
    st.subheader("Document")
    input_method = st.radio(
        "Input method",
        ["Upload PDF", "Enter URL"],
        label_visibility="collapsed",
    )

    uploaded_file = None
    pdf_url = ""

    if input_method == "Upload PDF":
        uploaded_file = st.file_uploader(
            "Upload PDF",
            type=["pdf"],
            label_visibility="collapsed",
            help="Drag & drop a PDF here, or click to browse.",
        )
        if uploaded_file:
            st.success(f"Ready: **{uploaded_file.name}**")
    else:
        pdf_url = st.text_input(
            "PDF URL",
            placeholder="https://example.com/document.pdf",
            label_visibility="collapsed",
        )

# ─── Main area ────────────────────────────────────────────────────────────────
st.title("Mistral OCR Showcase")
st.caption(
    "Extract structured text from a PDF using Mistral's OCR model, "
    "then chat about the content with GPT-4o."
)

# Readiness flags
has_document = (uploaded_file is not None) or bool(pdf_url.strip())
can_ocr = bool(mistral_key) and has_document

# ── OCR button ────────────────────────────────────────────────────────────────
ocr_btn = st.button(
    "Apply Mistral OCR",
    type="primary",
    disabled=not can_ocr,
    help=(
        "Add a Mistral API key and a document in the sidebar to enable."
        if not can_ocr
        else "Run OCR on the selected document."
    ),
)

if not has_document and not st.session_state.ocr_done:
    st.info(
        "Add your **Mistral API key** and select a **PDF document** in the sidebar "
        "to get started."
    )

if ocr_btn and can_ocr:
    with st.spinner("Running Mistral OCR — this may take a moment…"):
        try:
            pdf_bytes = uploaded_file.read() if uploaded_file else None
            url = pdf_url.strip() if not pdf_bytes else None

            result = _run_ocr(mistral_key, pdf_bytes=pdf_bytes, url=url)

            st.session_state.ocr_markdown = _combine_markdown(result)
            st.session_state.ocr_images = _build_image_map(result)
            st.session_state.ocr_done = True
            st.session_state.chat_history = []  # reset chat on new document
            st.rerun()
        except Exception as exc:
            st.error(f"OCR failed: {exc}")

# ── OCR results ───────────────────────────────────────────────────────────────
if st.session_state.ocr_done and st.session_state.ocr_markdown is not None:
    st.divider()
    st.subheader("OCR Results")

    rendered = _render_markdown_with_images(
        st.session_state.ocr_markdown,
        st.session_state.ocr_images,
    )
    st.markdown(rendered, unsafe_allow_html=True)

    with st.expander("View raw markdown"):
        st.code(st.session_state.ocr_markdown, language="markdown")

    # ── Chat section ──────────────────────────────────────────────────────────
    st.divider()

    hdr_col, clear_col = st.columns([5, 1])
    with hdr_col:
        st.subheader("Chat about this document")
        st.caption("Ask GPT-4o anything about the extracted text. Clear the thread to start fresh.")
    with clear_col:
        st.write("")  # vertical alignment nudge
        if st.button("Clear chat", help="Reset the conversation history"):
            st.session_state.chat_history = []
            st.rerun()

    if not openai_key:
        st.warning("Add your **OpenAI API key** in the sidebar to enable the chat.")
    else:
        # Display conversation history
        for q, a in st.session_state.chat_history:
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"):
                st.write(a)

        # Question input
        with st.form("chat_form", clear_on_submit=True):
            user_question = st.text_area(
                "Your question",
                placeholder="e.g. What is the main topic of this document?",
                height=90,
                label_visibility="collapsed",
            )
            submit_btn = st.form_submit_button("Submit", type="primary")

        if submit_btn and user_question.strip():
            with st.spinner("Thinking…"):
                try:
                    answer = _run_chat(
                        openai_key,
                        st.session_state.ocr_markdown,
                        user_question.strip(),
                        st.session_state.chat_history,
                    )
                    st.session_state.chat_history.append(
                        (user_question.strip(), answer)
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Chat failed: {exc}")
