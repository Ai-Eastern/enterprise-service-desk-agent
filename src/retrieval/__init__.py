"""Persistent retrieval with explicit BGE embeddings and Chroma."""

from .chroma_store import (
    CHROMA_PATH,
    COLLECTION_NAME,
    MODEL_NAME,
    MODEL_REVISION,
    QUERY_INSTRUCTION,
    SearchResult,
    chunk_document,
    ingest,
    parse_markdown,
    search,
)

__all__ = [
    "CHROMA_PATH",
    "COLLECTION_NAME",
    "MODEL_NAME",
    "MODEL_REVISION",
    "QUERY_INSTRUCTION",
    "SearchResult",
    "chunk_document",
    "ingest",
    "parse_markdown",
    "search",
]
