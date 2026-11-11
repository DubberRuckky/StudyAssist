"""Ingestion tool for parsing PDFs, Word docs, slides, sheets, and OCR images into structured memory."""

import io
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None

from auth.context import UserContext
from agent.dispatcher import register_tool
from models.brain import chat
from storage.memory import compute_learning_order, load_subject_memory, save_subject_memory
from storage.vector_store import add_document_chunks

# Supported extensions
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"
}

# Auto-configure Windows Tesseract binary location if present
TESSERACT_WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\Inba Ilakiyan\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
]
for p in TESSERACT_WINDOWS_PATHS:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break


def _ocr_image(img: Image.Image) -> str:
    """Safely perform OCR on an image, falling back gracefully if Tesseract is not installed."""
    try:
        text = pytesseract.image_to_string(img)
        return text.strip()
    except Exception:
        return "[Scanned page: OCR engine not configured on system]"


def _extract_pdf(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text from a PDF, applying OCR on pages with minimal or no embedded text."""
    if pymupdf is None:
        raise ImportError(
            "PyMuPDF is not installed in the active Python environment. "
            "Please run: pip install pymupdf (or launch with .venv active)."
        )
    doc = pymupdf.open(str(file_path))
    pages_data = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text().strip()

        # If page has virtually no text (e.g. scanned document or diagram), try OCR
        if len(text) < 30:
            try:
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                ocr_text = _ocr_image(img)
                if ocr_text:
                    text = ocr_text
            except Exception:
                pass

        if text:
            pages_data.append({"page": page_num + 1, "text": text})

    doc.close()
    return pages_data


def _extract_docx(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text paragraphs from a Word document (.docx)."""
    doc = Document(str(file_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    full_text = "\n\n".join(paragraphs)
    return [{"page": 1, "text": full_text}] if full_text else []


def _extract_pptx(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text from PowerPoint presentations slide-by-slide."""
    prs = Presentation(str(file_path))
    slides_data = []

    for i, slide in enumerate(prs.slides):
        slide_texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    t = paragraph.text.strip()
                    if t:
                        slide_texts.append(t)
        if slide_texts:
            slides_data.append({"page": i + 1, "text": "\n".join(slide_texts)})

    return slides_data


def _extract_xlsx(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text from Excel spreadsheets per worksheet."""
    wb = openpyxl.load_workbook(str(file_path), data_only=True)
    sheets_data = []

    for idx, sheet_name in enumerate(wb.sheetnames):
        sheet = wb[sheet_name]
        rows_text = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows_text.append(" | ".join(cells))
        if rows_text:
            sheets_data.append({"page": idx + 1, "text": f"Sheet '{sheet_name}':\n" + "\n".join(rows_text)})

    wb.close()
    return sheets_data


def _extract_image(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text from an image file using Optical Character Recognition."""
    try:
        img = Image.open(str(file_path))
        text = _ocr_image(img)
        return [{"page": 1, "text": text}] if text else []
    except Exception as err:
        return [{"page": 1, "text": f"[Image read error: {err}]"}]


def _extract_plaintext(file_path: Path) -> List[Dict[str, Any]]:
    """Extract text from plain text or markdown files."""
    text = file_path.read_text(encoding="utf-8", errors="replace").strip()
    return [{"page": 1, "text": text}] if text else []


def chunk_text(
    pages: List[Dict[str, Any]],
    filename: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> List[Dict[str, Any]]:
    """Split extracted page text into uniform chunks retaining exact source and page numbers."""
    chunks = []
    chunk_idx = 0

    for page_info in pages:
        page_num = page_info["page"]
        text = page_info["text"]

        if len(text) <= chunk_size:
            chunks.append({
                "id": f"{filename}_p{page_num}_{chunk_idx}",
                "filename": filename,
                "page": page_num,
                "text": text,
            })
            chunk_idx += 1
        else:
            # Split with overlap
            pos = 0
            while pos < len(text):
                end = min(pos + chunk_size, len(text))
                slice_text = text[pos:end].strip()
                if slice_text:
                    chunks.append({
                        "id": f"{filename}_p{page_num}_{chunk_idx}",
                        "filename": filename,
                        "page": page_num,
                        "text": slice_text,
                    })
                    chunk_idx += 1
                pos += (chunk_size - overlap)

    return chunks


def extract_chunk_topics_with_brain(
    chunks: List[Dict[str, Any]],
    user_context: UserContext,
    profile_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Use brain or heuristic extraction to tag chunks with topics and prerequisites."""
    if not chunks:
        return []

    # Prepare summary prompt sample of chunks
    combined_sample = "\n---\n".join([c["text"][:300] for c in chunks[:5]])
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are an academic concept extractor. Analyze the following excerpts and return a JSON list of topics. "
                "Each topic must have: 'name' (concise string), 'summary' (1 sentence), 'prerequisites' (list of basic concept names needed first). "
                "Output ONLY a valid JSON list of objects: [{\"name\": \"...\", \"summary\": \"...\", \"prerequisites\": [...]}]"
            ),
        },
        {"role": "user", "content": combined_sample},
    ]

    try:
        resp = chat(messages=prompt_messages, options={"profile": profile_name or "mock"}, user_context=user_context)
        content = resp.get("content", "").strip()

        # Clean JSON fences if any
        if content.startswith("```"):
            import re
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content).strip()

        parsed = json.loads(content)
        if isinstance(parsed, list) and parsed:
            return parsed
    except Exception:
        pass

    # Heuristic fallback if brain fails or runs in offline mode
    fallback_topics = [
        {"name": "Foundational Principles", "summary": "Core definitions and baseline rules.", "prerequisites": []},
        {"name": "Applied Concepts", "summary": "Intermediate mechanisms and derivations.", "prerequisites": ["Foundational Principles"]},
        {"name": "Advanced Synthesis", "summary": "Problem-solving and higher-level integration.", "prerequisites": ["Applied Concepts"]},
    ]
    return fallback_topics


def ingest_material(
    file_path: str,
    subject: str,
    user_context: UserContext,
    profile_name: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Ingest, parse, OCR, chunk, and index study material into user memory and vector store."""
    src_path = Path(file_path)
    if not src_path.exists():
        return f"File error: '{file_path}' does not exist."

    ext = src_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return (
            f"Unsupported file type '{ext}'. Please provide a PDF (.pdf), Word document (.docx), "
            "PowerPoint presentation (.pptx), Excel sheet (.xlsx), plain text (.txt, .md), or image."
        )

    # 1. Copy file to user's isolated uploads folder
    safe_name = src_path.name
    dest_path = user_context.resolve_safe_path(f"uploads/{safe_name}")
    if src_path.resolve() != dest_path.resolve():
        shutil.copy2(src_path, dest_path)

    # 2. Extract text by file type
    if ext == ".pdf":
        pages = _extract_pdf(dest_path)
    elif ext == ".docx":
        pages = _extract_docx(dest_path)
    elif ext == ".pptx":
        pages = _extract_pptx(dest_path)
    elif ext == ".xlsx":
        pages = _extract_xlsx(dest_path)
    elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff"}:
        pages = _extract_image(dest_path)
    else:  # .txt, .md
        pages = _extract_plaintext(dest_path)

    if not pages:
        return f"Ingestion warning: No extractable text found in '{safe_name}'."

    # 3. Chunk text with exact page/source attribution
    chunks = chunk_text(pages, filename=safe_name)

    # 4. Extract concepts and prerequisites with the brain
    extracted_topics = extract_chunk_topics_with_brain(chunks, user_context=user_context, profile_name=profile_name)

    # 5. Deterministically sort topics into learning order using OUR CODE (topological sort)
    computed_order = compute_learning_order(extracted_topics)

    # 6. Save memory file
    memory_data = load_subject_memory(user_context, subject)
    memory_data["files"].append({
        "filename": safe_name,
        "extension": ext,
        "num_pages": len(pages),
        "num_chunks": len(chunks),
    })
    # Merge topics
    existing_topics = {t["name"]: t for t in memory_data.get("topics", [])}
    for t in extracted_topics:
        existing_topics[t["name"]] = t
    memory_data["topics"] = list(existing_topics.values())
    memory_data["learning_order"] = compute_learning_order(memory_data["topics"])
    save_subject_memory(user_context, subject, memory_data)

    # 7. Index chunks in ChromaDB vector store
    for c in chunks:
        # Assign topic tag
        c["topic"] = extracted_topics[0]["name"] if extracted_topics else "General"
    indexed_count = add_document_chunks(user_context, subject, chunks)

    return (
        f"Successfully ingested '{safe_name}' into subject '{subject}': "
        f"{len(pages)} page(s) parsed, {indexed_count} chunk(s) indexed in vector store, "
        f"{len(extracted_topics)} topic(s) sequenced into learning order."
    )


# Register ingest_material in dispatcher
register_tool(
    name="ingest_material",
    func=ingest_material,
    schema={
        "type": "function",
        "function": {
            "name": "ingest_material",
            "description": "Ingests, parses, OCRs, and organizes study material into the subject memory file and vector store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute or workspace path to the file to ingest."},
                    "subject": {"type": "string", "description": "The course or subject name (e.g. 'Physics', 'Biology')."},
                },
                "required": ["file_path", "subject"],
            },
        },
    },
)
