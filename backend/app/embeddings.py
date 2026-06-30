"""
Local embedding model wrapper.

Why local instead of an API: Groq does not offer embeddings, and calling
a paid embedding API for every product/page chunk across many tenants adds
recurring cost + another point of failure. sentence-transformers runs
on your own server, is free, and is fast enough for this workload.

Model is loaded once (singleton) and reused across requests.
"""
from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

from . import config


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    # Cached so the ~80MB model is loaded into memory only once per process,
    # not on every request.
    return SentenceTransformer(config.EMBEDDING_MODEL_NAME)


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts. Returns list of float vectors."""
    if not texts:
        return []
    model = get_embedder()
    vectors = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return vectors.tolist()


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
