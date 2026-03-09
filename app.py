import re

import streamlit as st
from ocr_chat_api import run_chat, run_ocr

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lab Results Extractor",
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
    "chat_input": "",
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Lab Results Extractor")
    st.caption("Configure your keys, then upload a lab report PDF for extraction.")

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
    st.subheader("Lab Report Input")
    input_method = st.radio(
        "Input method",
        ["Upload PDF", "Enter URL"],
        label_visibility="collapsed",
    )

    uploaded_file = None
    pdf_url = ""

    if input_method == "Upload PDF":
        uploaded_file = st.file_uploader(
            "Upload lab report PDF",
            type=["pdf"],
            label_visibility="collapsed",
            help="Drag and drop a lab result PDF, or click to browse.",
        )
        if uploaded_file:
            st.success(f"Ready: **{uploaded_file.name}**")
    else:
        pdf_url = st.text_input(
            "Lab report PDF URL",
            placeholder="https://example.com/lab-results.pdf",
            label_visibility="collapsed",
        )

# ─── Main area ────────────────────────────────────────────────────────────────
st.title("Lab Results Information Extractor")
st.caption(
    "Extract text from laboratory reports with Mistral OCR, then use GPT-4o to "
    "identify biomarkers, reference ranges, out-of-range values, trends, and follow-up questions."
)

# Readiness flags
has_document = (uploaded_file is not None) or bool(pdf_url.strip())
can_ocr = bool(mistral_key) and has_document

# ── OCR button ────────────────────────────────────────────────────────────────
ocr_btn = st.button(
    "Extract Lab Report Text",
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
        "Add your **Mistral API key** and select a **lab report PDF** in the sidebar "
        "to start extraction."
    )

if ocr_btn and can_ocr:
    with st.spinner("Extracting lab report text with Mistral OCR..."):
        try:
            pdf_bytes = uploaded_file.read() if uploaded_file else None
            url = pdf_url.strip() if not pdf_bytes else None

            result = run_ocr(mistral_key, pdf_bytes=pdf_bytes, url=url)

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
    st.subheader("Extracted Lab Report Text")

    with st.expander("Parsed content (click to view)", expanded=False):
        rendered = _render_markdown_with_images(
            st.session_state.ocr_markdown,
            st.session_state.ocr_images,
        )
        st.markdown(rendered, unsafe_allow_html=True)
        st.caption("Raw extracted markdown")
        st.code(st.session_state.ocr_markdown, language="markdown")

    # ── Chat section ──────────────────────────────────────────────────────────
    st.divider()

    hdr_col, clear_col = st.columns([5, 1])
    with hdr_col:
        st.subheader("Lab Result Extraction Assistant")
        st.caption("Ask GPT-4o to extract structured findings from the report. Clear the thread to start fresh.")
    with clear_col:
        st.write("")  # vertical alignment nudge
        if st.button("Clear chat", help="Reset the conversation history"):
            st.session_state.chat_history = []
            st.session_state.chat_input = ""
            st.rerun()

    st.write("Quick extraction prompts:")
    prompt_cols = st.columns(3)
    prompt_options = [
        "Extract all biomarkers with result, unit, and reference range in a table.",
        "List all abnormal or out-of-range values and explain why each is abnormal.",
        "Summarize key findings and suggested follow-up questions for my doctor.",
    ]
    for idx, prompt in enumerate(prompt_options):
        with prompt_cols[idx]:
            if st.button(f"Use prompt {idx + 1}", key=f"quick_prompt_{idx}"):
                st.session_state.chat_input = prompt
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
                placeholder="e.g. Extract CBC and CMP values with flags for high/low results.",
                height=90,
                label_visibility="collapsed",
                key="chat_input",
            )
            submit_btn = st.form_submit_button("Submit", type="primary")

        if submit_btn and user_question.strip():
            with st.spinner("Thinking…"):
                try:
                    answer = run_chat(
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
