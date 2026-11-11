"""Search notes tool retrieving relevant study excerpts with page and file citations."""

from typing import Any, Dict, List, Optional
from auth.context import UserContext
from agent.dispatcher import register_tool
from storage.vector_store import query_document_chunks


def search_notes(
    query: str,
    subject: str,
    user_context: UserContext,
    n_results: int = 4,
    **kwargs: Any,
) -> str:
    """Find and format relevant study passages from ChromaDB with file and page citations."""
    results = query_document_chunks(
        context=user_context,
        subject=subject,
        query_text=query,
        n_results=n_results,
    )

    if not results:
        return f"No relevant notes found for subject '{subject}' matching '{query}'."

    formatted_passages = []
    for idx, item in enumerate(results, start=1):
        filename = item.get("filename", "unknown_source")
        page = item.get("page", 1)
        topic = item.get("topic", "General")
        text = item.get("text", "").strip()

        citation_header = f"[Excerpt {idx} | Source: {filename}, Page: {page}, Topic: {topic}]"
        formatted_passages.append(f"{citation_header}\n{text}")

    return "\n\n---\n\n".join(formatted_passages)


# Register search_notes in dispatcher
register_tool(
    name="search_notes",
    func=search_notes,
    schema={
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Searches the student's indexed notes in ChromaDB and returns relevant passages with file and page citations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The concept, question, or keyword to search for."},
                    "subject": {"type": "string", "description": "The subject name to search within (e.g. 'Physics')."},
                    "n_results": {"type": "integer", "description": "Number of passages to return (default 4)."},
                },
                "required": ["query", "subject"],
            },
        },
    },
)
