"""User-isolated vector database client and embedding retrieval using ChromaDB."""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
import requests
import chromadb
from chromadb.config import Settings as ChromaSettings

from auth.context import UserContext
from config.loader import load_settings_config

logger = logging.getLogger(__name__)


def _generate_fallback_embedding(text: str, dim: int = 128) -> List[float]:
    """Generate a deterministic, offline synthetic embedding vector for unit testing."""
    # Use sha256 hashes of text slices to generate reproducible floats
    vector = []
    base_hash = hashlib.sha256(text.encode("utf-8")).digest()
    for i in range(dim):
        byte_val = base_hash[i % len(base_hash)]
        val = (float(byte_val) / 255.0) * 2.0 - 1.0
        vector.append(round(val, 6))
    return vector


def get_embedding(text: str, use_cpu: Optional[bool] = None) -> List[float]:
    """Compute embeddings via Ollama nomic-embed-text or return deterministic offline fallback."""
    settings = load_settings_config().get("embeddings", {})
    ollama_url = settings.get("ollama_url", "http://localhost:11434")
    model_name = settings.get("model", "nomic-embed-text")

    try:
        payload = {
            "model": model_name,
            "prompt": text,
        }
        resp = requests.post(f"{ollama_url}/api/embeddings", json=payload, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "embedding" in data:
                return data["embedding"]
    except Exception:
        # Offline or Ollama endpoint not active; use deterministic fallback
        pass

    return _generate_fallback_embedding(text)


def get_user_vector_client(context: UserContext) -> chromadb.PersistentClient:
    """Create a private ChromaDB persistent client pointing to the user's isolated directory."""
    chroma_path = str(context.chroma_dir.resolve())
    return chromadb.PersistentClient(
        path=chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True)
    )


def _sanitize_collection_name(subject: str) -> str:
    """Format a subject name into a valid ChromaDB collection identifier."""
    # Chroma requires 3-63 characters, letters, numbers, underscores or hyphens
    clean = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in subject.strip().lower())
    if len(clean) < 3:
        clean = f"subj_{clean}"
    return clean[:63]


def get_subject_collection(context: UserContext, subject: str) -> chromadb.Collection:
    """Retrieve or create a ChromaDB collection for the given subject."""
    client = get_user_vector_client(context)
    col_name = _sanitize_collection_name(subject)
    return client.get_or_create_collection(
        name=col_name,
        metadata={"subject": subject.strip()}
    )


def add_document_chunks(
    context: UserContext,
    subject: str,
    chunks: List[Dict[str, Any]],
) -> int:
    """Add text chunks with page citations and embeddings to the user's subject collection."""
    if not chunks:
        return 0

    collection = get_subject_collection(context, subject)
    ids = []
    documents = []
    metadatas = []
    embeddings = []

    for i, chunk in enumerate(chunks):
        chunk_id = chunk.get("id") or f"{chunk.get('filename', 'doc')}_{chunk.get('page', 0)}_{i}_{int(hashlib.md5(chunk['text'].encode()).hexdigest()[:8], 16)}"
        text = chunk["text"]
        metadata = {
            "filename": str(chunk.get("filename", "unknown")),
            "page": int(chunk.get("page", 1)),
            "topic": str(chunk.get("topic", "General")),
            "subject": subject.strip(),
        }
        embedding = chunk.get("embedding") or get_embedding(text)

        ids.append(chunk_id)
        documents.append(text)
        metadatas.append(metadata)
        embeddings.append(embedding)

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    return len(ids)


def query_document_chunks(
    context: UserContext,
    subject: str,
    query_text: str,
    n_results: int = 4,
) -> List[Dict[str, Any]]:
    """Search for relevant document passages in ChromaDB matching the user's query."""
    collection = get_subject_collection(context, subject)
    if collection.count() == 0:
        return []

    query_vec = get_embedding(query_text)
    effective_k = min(n_results, collection.count())
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=effective_k,
        include=["documents", "metadatas", "distances"],
    )

    formatted = []
    if results and "documents" in results and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        dists = results["distances"][0] if results.get("distances") else [0.0] * len(docs)

        for doc, meta, dist in zip(docs, metas, dists):
            formatted.append({
                "text": doc,
                "filename": meta.get("filename", "unknown"),
                "page": meta.get("page", 1),
                "topic": meta.get("topic", "General"),
                "subject": meta.get("subject", subject),
                "distance": dist,
            })
    return formatted


def delete_subject_collection(context: UserContext, subject: str) -> None:
    """Delete an entire subject vector collection from ChromaDB."""
    client = get_user_vector_client(context)
    col_name = _sanitize_collection_name(subject)
    try:
        client.delete_collection(name=col_name)
    except Exception:
        pass
