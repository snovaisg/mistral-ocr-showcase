import io
import re
import time
import zipfile

import streamlit as st
from ocr_chat_api import run_chat, run_document_extraction, run_ocr

# --- Page config -------------------------------------------------------------
st.set_page_config(
    page_title="Lab Results Extractor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Minimal CSS tweaks ------------------------------------------------------
st.markdown(
    """
    <style>
        section[data-testid="stSidebar"] .stButton > button { width: 100%; }
        .chat-user   { background:#e8f4fd; padding:.75rem 1rem; border-radius:8px; margin-bottom:.4rem; }
        .chat-assist { background:#f4f4f4; padding:.75rem 1rem; border-radius:8px; margin-bottom:.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Session-state defaults --------------------------------------------------
for _k, _v in {
    "ocr_markdown": None,
    "ocr_images": {},
    "ocr_done": False,
    "chat_history": [],
    "chat_input": "",
    "batch_results": [],
    "batch_done": False,
    "batch_prompt_preview": "",
    "batch_skipped_files": [],
    "batch_ignored_system_files": 0,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# --- Helpers -----------------------------------------------------------------
def _combine_markdown(ocr_response) -> str:
    """Concatenate all pages' markdown with page dividers."""
    parts = []
    for i, page in enumerate(ocr_response.pages):
        if len(ocr_response.pages) > 1:
            parts.append(f"\n\n---\n*-- Page {i + 1} --*\n\n")
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
    """Replace ![alt](img_id) references with inline HTML <img> tags."""

    def _replace(match):
        alt = match.group(1)
        img_id = match.group(2)
        if img_id in images:
            return _img_tag(images[img_id], alt)
        return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, markdown)


def _parse_requested_fields(request_text: str) -> list[str]:
    """Split free-form extraction request into explicit field items."""
    raw = request_text.strip()
    if not raw:
        return []

    # Remove generic lead-in clause when text is in "lead-in: actual request" form.
    if ":" in raw:
        lead, remainder = raw.split(":", 1)
        if remainder.strip() and 1 <= len(lead.strip().split()) <= 8:
            raw = remainder.strip()
    raw = re.sub(
        r"(?i)\b(from each pdf|for each pdf|for each document|from each document)\b",
        "",
        raw,
    )

    # Normalize common separators to newlines.
    normalized = raw
    normalized = re.sub(r"(?i)\s+(and|as well as)\s+", "\n", normalized)
    normalized = normalized.replace(";", "\n").replace("|", "\n").replace("&", "\n")
    normalized = normalized.replace(",", "\n")

    fields: list[str] = []
    for raw_line in normalized.splitlines():
        cleaned = re.sub(r"^\s*[-*\d.)]+\s*", "", raw_line).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
        if cleaned:
            fields.append(cleaned)

    deduped: list[str] = []
    seen = set()
    for field in fields:
        low = field.lower()
        if low in seen:
            continue
        seen.add(low)
        deduped.append(field)
    return deduped


def _summarize_extraction_request(user_request: str) -> tuple[list[str], str]:
    """Return parsed fields and a concise summary of the extraction plan."""
    fields = _parse_requested_fields(user_request)
    if fields:
        preview = ", ".join(fields[:6])
        suffix = "..." if len(fields) > 6 else ""
        summary = f"{len(fields)} field(s) will be extracted per PDF: {preview}{suffix}"
        return fields, summary

    fallback = user_request.strip()
    summary = f"Free-form extraction request per PDF: {fallback}"
    return [], summary


def _format_batch_prompt(user_request: str) -> str:
    """Convert user query into a direct per-document extraction instruction."""
    fields, _ = _summarize_extraction_request(user_request)
    if fields:
        bullets = "\n".join(f"- {f}" for f in fields)
        return (
            "Extract each field below from this single document.\n"
            "Before extracting, normalize each field label by removing conversational lead-ins "
            "or framing text and keep only the minimal task descriptor.\n"
            "Return one result per field, even if missing.\n"
            "If missing, use value exactly 'not found in document' and status 'not_found'.\n\n"
            "Requested fields:\n"
            f"{bullets}"
        )

    return (
        "Extract the information requested below from this single document.\n"
        "First normalize the request by removing conversational lead-ins and keep only "
        "the minimal task descriptors.\n"
        "When any requested item is missing, return value exactly 'not found in document' "
        "and status 'not_found'.\n\n"
        "Request:\n"
        f"{user_request.strip()}"
    )


def _read_pdf_zip(zip_bytes: bytes) -> tuple[list[tuple[str, bytes]], list[str], int]:
    """Read a ZIP and return PDF payloads and skipped non-PDF file names."""
    max_files = 60
    max_total_uncompressed = 120 * 1024 * 1024

    pdf_docs: list[tuple[str, bytes]] = []
    skipped_files: list[str] = []
    ignored_system_files = 0
    total_uncompressed = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        user_files = []
        for info in infos:
            path = info.filename
            filename = path.split("/")[-1]
            if (
                path.startswith("__MACOSX/")
                or filename.startswith("._")
                or filename.startswith(".DS_Store")
                or filename.startswith(".")
            ):
                ignored_system_files += 1
                continue
            user_files.append(info)

        if len(user_files) > max_files:
            raise ValueError(f"ZIP has {len(user_files)} files. Max allowed is {max_files}.")

        for info in user_files:
            filename = info.filename.split("/")[-1]
            if not filename:
                continue

            total_uncompressed += info.file_size
            if total_uncompressed > max_total_uncompressed:
                raise ValueError("ZIP is too large after decompression. Limit is 120 MB.")

            if not filename.lower().endswith(".pdf"):
                skipped_files.append(filename)
                continue

            with zf.open(info, "r") as file_obj:
                pdf_docs.append((filename, file_obj.read()))

    if not pdf_docs:
        raise ValueError("No PDF files found in ZIP.")

    return pdf_docs, skipped_files, ignored_system_files


# --- Sidebar -----------------------------------------------------------------
with st.sidebar:
    st.title("Lab Results Extractor")
    st.caption("Configure your keys, then choose single-document or batch extraction.")

    st.subheader("API Keys")
    mistral_key = st.text_input(
        "Mistral API Key",
        type="password",
        placeholder="Enter your Mistral API key...",
        help="Required for OCR. Get yours at console.mistral.ai",
    )
    openai_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="Enter your OpenAI API key...",
        help="Required for chat and batch extraction. Get yours at platform.openai.com",
    )

    st.divider()

    st.subheader("Lab Report Input")
    input_method = st.radio(
        "Input method",
        ["Upload PDF", "Enter URL", "Upload ZIP (Batch)"],
        label_visibility="collapsed",
    )

    uploaded_file = None
    pdf_url = ""
    uploaded_zip = None

    if input_method == "Upload PDF":
        uploaded_file = st.file_uploader(
            "Upload lab report PDF",
            type=["pdf"],
            label_visibility="collapsed",
            help="Drag and drop a lab result PDF, or click to browse.",
        )
        if uploaded_file:
            st.success(f"Ready: **{uploaded_file.name}**")
    elif input_method == "Enter URL":
        pdf_url = st.text_input(
            "Lab report PDF URL",
            placeholder="https://example.com/lab-results.pdf",
            label_visibility="collapsed",
        )
    else:
        uploaded_zip = st.file_uploader(
            "Upload ZIP with PDF files",
            type=["zip"],
            label_visibility="collapsed",
            help="Upload a ZIP containing PDF files. Non-PDF files are ignored.",
        )
        if uploaded_zip:
            st.success(f"Ready: **{uploaded_zip.name}**")


# --- Main area ---------------------------------------------------------------
st.title("Lab Results Information Extractor")

if input_method == "Upload ZIP (Batch)":
    st.caption(
        "Batch mode: OCR each PDF in a ZIP and extract your requested fields from each document."
    )
    st.info(
        "HF Spaces allows ZIP uploads via Streamlit file uploader. "
        "This app processes ZIPs in-memory, accepts only .pdf entries, and enforces size/file-count limits."
    )
    st.caption(
        "Rate limiting: calls to the same provider are automatically spaced by at least 5 seconds."
    )

    batch_request = st.text_area(
        "What do you want to extract from each PDF?",
        placeholder=(
            "Examples:\n"
            "- Patient name\n"
            "- Collection date\n"
            "- Hemoglobin value\n"
            "- HbA1c\n"
        ),
        height=140,
    )

    if batch_request.strip():
        parsed_fields, request_summary = _summarize_extraction_request(batch_request)
        st.info(f"Task summary: {request_summary}")
        if parsed_fields:
            st.caption("Parsed fields")
            st.code("\n".join(f"- {field}" for field in parsed_fields), language="text")
        st.session_state.batch_prompt_preview = _format_batch_prompt(batch_request)
        with st.expander("Per-document prompt format", expanded=False):
            st.code(st.session_state.batch_prompt_preview, language="text")

    can_batch = bool(mistral_key and openai_key and uploaded_zip and batch_request.strip())
    run_batch_btn = st.button(
        "Run Batch Extraction",
        type="primary",
        disabled=not can_batch,
        help=(
            "Add Mistral key, OpenAI key, ZIP file, and extraction request to enable."
            if not can_batch
            else "Run OCR + extraction for each PDF in ZIP."
        ),
    )

    if run_batch_btn and can_batch:
        try:
            pdf_docs, skipped_files, ignored_system_files = _read_pdf_zip(uploaded_zip.getvalue())
            st.session_state.batch_results = []
            st.session_state.batch_skipped_files = skipped_files
            st.session_state.batch_ignored_system_files = ignored_system_files

            progress = st.progress(0.0, text="Preparing batch run...")
            status = st.empty()
            phase_msg = st.empty()

            formatted_request = _format_batch_prompt(batch_request)
            total = len(pdf_docs)
            total_phases = total * 2
            phase_idx = 0
            started_ts = time.time()
            with st.status("Batch extraction is running...", expanded=True) as batch_status:
                for i, (filename, pdf_bytes) in enumerate(pdf_docs, start=1):
                    status.info(f"Processing {i}/{total}: {filename}")
                    try:
                        phase_idx += 1
                        phase_msg.info(f"[{i}/{total}] OCR parsing: {filename}")
                        progress.progress(
                            phase_idx / total_phases,
                            text=f"OCR step {i}/{total}: {filename}",
                        )
                        batch_status.write(f"OCR started for `{filename}`")
                        ocr_result = run_ocr(mistral_key, pdf_bytes=pdf_bytes)
                        markdown = _combine_markdown(ocr_result)

                        phase_idx += 1
                        phase_msg.info(f"[{i}/{total}] Extracting requested fields: {filename}")
                        progress.progress(
                            phase_idx / total_phases,
                            text=f"Extraction step {i}/{total}: {filename}",
                        )
                        batch_status.write(f"Field extraction started for `{filename}`")
                        extracted = run_document_extraction(
                            openai_key,
                            markdown,
                            formatted_request,
                        )
                        fields = extracted.get("fields", []) if isinstance(extracted, dict) else []
                        st.session_state.batch_results.append(
                            {
                                "file_name": filename,
                                "fields": fields,
                                "error": None,
                            }
                        )
                        batch_status.write(f"Completed `{filename}`")
                    except Exception as exc:
                        st.session_state.batch_results.append(
                            {
                                "file_name": filename,
                                "fields": [],
                                "error": str(exc),
                            }
                        )
                        batch_status.write(f"Failed `{filename}`: {exc}")

                elapsed = round(time.time() - started_ts, 1)
                batch_status.update(
                    label=f"Batch extraction completed in {elapsed}s",
                    state="complete",
                    expanded=False,
                )

            phase_msg.success("All documents finished. Rendering results...")
            progress.progress(1.0, text="Batch finished")
            status.success("Batch extraction completed.")
            st.session_state.batch_done = True
        except zipfile.BadZipFile:
            st.error("Invalid ZIP file.")
        except Exception as exc:
            st.error(f"Batch extraction failed: {exc}")

    if st.session_state.batch_done and st.session_state.batch_results:
        st.divider()
        st.subheader("Batch Extraction Results")

        if st.session_state.batch_skipped_files:
            st.warning(
                "Skipped non-PDF files: "
                + ", ".join(st.session_state.batch_skipped_files[:20])
                + (" ..." if len(st.session_state.batch_skipped_files) > 20 else "")
            )
        if st.session_state.batch_ignored_system_files:
            st.caption(
                f"Ignored hidden/system ZIP entries: {st.session_state.batch_ignored_system_files}"
            )

        success_count = len([r for r in st.session_state.batch_results if not r["error"]])
        error_count = len(st.session_state.batch_results) - success_count
        st.caption(f"Processed {len(st.session_state.batch_results)} PDF files. Success: {success_count}. Failed: {error_count}.")

        all_rows = []
        for result in st.session_state.batch_results:
            if result["error"]:
                all_rows.append(
                    {
                        "File": result["file_name"],
                        "Field": "",
                        "Value": "",
                        "Status": "error",
                        "Evidence": result["error"],
                    }
                )
                continue
            for field in result["fields"]:
                all_rows.append(
                    {
                        "File": result["file_name"],
                        "Field": field.get("field", ""),
                        "Value": field.get("value", ""),
                        "Status": field.get("status", ""),
                        "Evidence": field.get("evidence", ""),
                    }
                )

        for result in st.session_state.batch_results:
            label = result["file_name"]
            with st.expander(label, expanded=False):
                if result["error"]:
                    st.error(result["error"])
                    continue

                rows = []
                for field in result["fields"]:
                    rows.append(
                        {
                            "Field": field.get("field", ""),
                            "Value": field.get("value", ""),
                            "Status": field.get("status", ""),
                            "Evidence": field.get("evidence", ""),
                        }
                    )

                if rows:
                    st.table(rows)
                else:
                    st.info("No structured fields were returned for this document.")

        st.divider()
        st.subheader("Final Consolidated Table")
        if all_rows:
            st.dataframe(all_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No rows available for consolidated output.")

    st.stop()

st.caption(
    "Extract text from laboratory reports with Mistral OCR, then use GPT-4o to "
    "identify biomarkers, reference ranges, out-of-range values, trends, and follow-up questions."
)

# Readiness flags
has_document = (uploaded_file is not None) or bool(pdf_url.strip())
can_ocr = bool(mistral_key) and has_document

# --- OCR button --------------------------------------------------------------
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
            st.session_state.chat_history = []
            st.rerun()
        except Exception as exc:
            st.error(f"OCR failed: {exc}")

# --- OCR results -------------------------------------------------------------
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

    st.divider()

    hdr_col, clear_col = st.columns([5, 1])
    with hdr_col:
        st.subheader("Lab Result Extraction Assistant")
        st.caption("Ask GPT-4o to extract structured findings from the report. Clear the thread to start fresh.")
    with clear_col:
        st.write("")
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
        for q, a in st.session_state.chat_history:
            with st.chat_message("user"):
                st.write(q)
            with st.chat_message("assistant"):
                st.write(a)

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
            with st.spinner("Thinking..."):
                try:
                    answer = run_chat(
                        openai_key,
                        st.session_state.ocr_markdown,
                        user_question.strip(),
                        st.session_state.chat_history,
                    )
                    st.session_state.chat_history.append((user_question.strip(), answer))
                    st.rerun()
                except Exception as exc:
                    st.error(f"Chat failed: {exc}")
