# Agent Tools (`tools/`)

This directory houses the six canonical tools exposed to StudyAssist's agent loop.

## Tool Registry
1. `ingest_material.py`: Ingests and parses PDFs, Word documents (.docx), presentation slides (.pptx), spreadsheets (.xlsx), plain text/markdown, and images (OCR via pytesseract). Chunks text with exact source and page/slide numbers, extracts concepts with the LLM, and sorts them into a learning order using deterministic graph logic.
2. `search_notes.py`: Queries the user's isolated ChromaDB vector collection to retrieve semantically matching study passages with citations.
3. `run_jury.py`: Coordinates a panel of 6 role-based sub-agents (explainer, rigorous expert, skeptic, exam coach, example builder, fact-checker) through independent answering, blind peer reviews, and weighted synthesis.
4. `generate_quiz.py`: Generates grounded quiz questions (multiple choice, open ended) from user notes, validates JSON output with retries, and evaluates student answers.
5. `schedule_revision.py`: Generates spaced-repetition revision schedules based on weak topics, target exam date, and daily study hours; exports an `.ics` calendar file. **Requires Human Confirmation before committing.**
6. `track_progress.py`: Stores quiz scores, timestamps, and calculates weak subject areas requiring revision.

## What to Edit
- To modify how files are parsed or chunked, edit `tools/ingest_material.py`.
- To adjust spaced repetition intervals or calendar format, edit `tools/schedule_revision.py`.
- To modify quiz prompt formatting, edit `tools/generate_quiz.py`.
