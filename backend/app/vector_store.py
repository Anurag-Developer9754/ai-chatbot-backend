"""
Vector store wrapper around ChromaDB.

CRITICAL DESIGN DECISION: one ChromaDB collection per tenant_id.
This is what prevents Client A's product data from ever leaking into
Client B's chatbot answers. Never put all tenants in a single shared
collection with a "tenant_id" metadata filter only — a bug in the filter
logic would leak data across clients. Physical collection separation is
a stronger guarantee.
"""
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings

from . import config
from .embeddings import embed_texts, embed_query

_client = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=config.CHROMA_DB_PATH)
    return _client


def _collection_name(tenant_id: str) -> str:
    # Chroma collection names must be alnum/underscore/hyphen, 3-63 chars.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant_id)
    return f"tenant_{safe}"[:63]


def get_collection(tenant_id: str):
    client = get_client()
    return client.get_or_create_collection(
        name=_collection_name(tenant_id),
        metadata={"hnsw:space": "cosine"},  # cosine distance, works well with normalized embeddings
    )


def upsert_chunks(
    tenant_id: str,
    ids: List[str],
    texts: List[str],
    metadatas: List[Dict[str, Any]],
):
    """Embed and store/update chunks for a tenant."""
    if not texts:
        return
    collection = get_collection(tenant_id)
    vectors = embed_texts(texts)
    collection.upsert(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)


def query(
    tenant_id: str,
    query_text: str,
    n_results: int = config.TOP_K_RETRIEVAL,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Semantic search within ONE tenant's collection only."""
    collection = get_collection(tenant_id)
    if collection.count() == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    query_vector = embed_query(query_text)
    result = collection.query(
        query_embeddings=[query_vector],
        n_results=min(n_results, max(collection.count(), 1)),
        where=where,
    )
    return result


def delete_tenant_collection(tenant_id: str):
    client = get_client()
    try:
        client.delete_collection(_collection_name(tenant_id))
    except Exception:
        pass  # collection may not exist yet
