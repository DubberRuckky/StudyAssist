"""Unit tests for Milestone 6: File ingestion, OCR, chunking, topic sequencing, and search notes."""

import pymupdf
from docx import Document
from pptx import Presentation
import openpyxl
from PIL import Image, ImageDraw
import pytest

from auth.context import UserContext
from storage.memory import load_subject_memory, update_learning_order
from tools.ingest_material import ingest_material
from tools.search_notes import search_notes


@pytest.fixture
def ingest_test_user(tmp_path):
    """Create a temporary user context and test fixtures directory."""
    data_root = tmp_path / "data"
    user = UserContext.create("test-ingest-user", "Sam", data_root=data_root)
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    return user, fixtures_dir


def test_ingest_text_and_markdown(ingest_test_user):
    """Verify ingestion of plain text and markdown notes."""
    user, fixtures = ingest_test_user
    txt_file = fixtures / "mechanics.txt"
    txt_file.write_text("Velocity is the rate of change of displacement. Acceleration is the rate of change of velocity.", encoding="utf-8")

    res = ingest_material(str(txt_file), "Physics", user_context=user)
    assert "Successfully ingested" in res
    assert "mechanics.txt" in res

    # Verify memory file
    mem = load_subject_memory(user, "Physics")
    assert len(mem["files"]) == 1
    assert len(mem["learning_order"]) > 0

    # Search notes
    search_res = search_notes("rate of change of velocity", "Physics", user_context=user)
    assert "mechanics.txt" in search_res
    assert "Page: 1" in search_res


def test_ingest_docx(ingest_test_user):
    """Verify ingestion of Word (.docx) documents."""
    user, fixtures = ingest_test_user
    docx_file = fixtures / "cells.docx"
    doc = Document()
    doc.add_heading("Cellular Biology", level=1)
    doc.add_paragraph("The cell membrane regulates the entry and exit of substances through osmosis and active transport.")
    doc.save(str(docx_file))

    res = ingest_material(str(docx_file), "Biology", user_context=user)
    assert "Successfully ingested" in res
    assert "cells.docx" in res

    search_res = search_notes("cell membrane osmosis", "Biology", user_context=user)
    assert "cells.docx" in search_res


def test_ingest_pptx(ingest_test_user):
    """Verify slide-by-slide ingestion and page tracking of PowerPoint presentations."""
    user, fixtures = ingest_test_user
    pptx_file = fixtures / "presentation.pptx"
    prs = Presentation()
    # Slide 1
    slide1 = prs.slides.add_slide(prs.slide_layouts[0])
    slide1.shapes.title.text = "Microeconomics: Supply and Demand"
    # Slide 2
    slide2 = prs.slides.add_slide(prs.slide_layouts[1])
    slide2.shapes.title.text = "Market Equilibrium"
    slide2.shapes.placeholders[1].text = "Equilibrium is reached when quantity supplied equals quantity demanded."
    prs.save(str(pptx_file))

    res = ingest_material(str(pptx_file), "Economics", user_context=user)
    assert "Successfully ingested" in res
    assert "presentation.pptx" in res

    search_res = search_notes("quantity supplied equals quantity demanded", "Economics", user_context=user)
    assert "presentation.pptx" in search_res
    assert "Page: 2" in search_res  # slide 2


def test_ingest_xlsx(ingest_test_user):
    """Verify sheet-by-sheet ingestion of Excel spreadsheets."""
    user, fixtures = ingest_test_user
    xlsx_file = fixtures / "financials.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BalanceSheet"
    ws.append(["Asset", "Value_USD"])
    ws.append(["Cash", "150000"])
    ws.append(["Inventory", "85000"])
    wb.save(str(xlsx_file))

    res = ingest_material(str(xlsx_file), "Finance", user_context=user)
    assert "Successfully ingested" in res
    assert "financials.xlsx" in res

    search_res = search_notes("Cash inventory balance", "Finance", user_context=user)
    assert "financials.xlsx" in search_res


def test_ingest_pdf(ingest_test_user):
    """Verify multi-page PDF text extraction with PyMuPDF."""
    user, fixtures = ingest_test_user
    pdf_file = fixtures / "calculus.pdf"
    doc = pymupdf.open()

    page1 = doc.new_page()
    page1.insert_text((50, 50), "Derivatives measure the instantaneous rate of change of a function.", fontsize=12)

    page2 = doc.new_page()
    page2.insert_text((50, 50), "Integrals compute the accumulation of quantities and areas under curves.", fontsize=12)

    doc.save(str(pdf_file))
    doc.close()

    res = ingest_material(str(pdf_file), "Mathematics", user_context=user)
    assert "Successfully ingested" in res
    assert "calculus.pdf" in res

    # Verify both pages indexed
    search_p1 = search_notes("derivatives instantaneous", "Mathematics", user_context=user)
    assert "Page: 1" in search_p1

    search_p2 = search_notes("integrals accumulation", "Mathematics", user_context=user)
    assert "Page: 2" in search_p2


def test_ingest_image_ocr(ingest_test_user):
    """Verify image ingestion and OCR scan handling."""
    user, fixtures = ingest_test_user
    img_file = fixtures / "diagram.png"
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "OCR Test Text", fill=(0, 0, 0))
    img.save(str(img_file))

    res = ingest_material(str(img_file), "ComputerScience", user_context=user)
    assert "Successfully ingested" in res
    assert "diagram.png" in res


def test_unsupported_file_type_plain_error(ingest_test_user):
    """Verify that unsupported file extensions produce a helpful plain-language error."""
    user, fixtures = ingest_test_user
    bad_file = fixtures / "model.bin"
    bad_file.write_bytes(b"\x00\x01\x02")

    res = ingest_material(str(bad_file), "General", user_context=user)
    assert "Unsupported file type '.bin'" in res


def test_student_can_override_topic_order(ingest_test_user):
    """Verify that the student can manually override the sequenced learning order."""
    user, fixtures = ingest_test_user
    txt_file = fixtures / "concepts.txt"
    txt_file.write_text("Topic 1 details. Topic 2 details.", encoding="utf-8")
    ingest_material(str(txt_file), "History", user_context=user)

    mem_before = load_subject_memory(user, "History")
    original_order = list(mem_before["learning_order"])

    # Override order
    reversed_order = list(reversed(original_order))
    update_learning_order(user, "History", reversed_order)

    mem_after = load_subject_memory(user, "History")
    assert mem_after["learning_order"] == reversed_order
