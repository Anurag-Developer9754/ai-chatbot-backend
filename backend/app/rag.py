"""
RAG pipeline orchestration — ties together vector_store, llm, and db.

This is where the "strictness" actually gets enforced:
  1. Retrieve top-K chunks for the query.
  2. If nothing relevant enough was found -> return fallback WITHOUT calling
     the LLM at all (saves cost, guarantees no hallucinated answer).
  3. Always inject manual facts (coupons/contact/hours) when relevant,
     since those are too important to depend on crawl quality alone.
  4. Call Groq with strict system prompt + bounded conversation history.
  5. Attach structured product cards (from metadata, never from LLM text)
     so links/prices in the UI are always exactly what's in the database.
"""
from typing import List, Dict
from . import config, db, llm
from .vector_store import query as vector_query


def _is_relevant(distances: List[float]) -> bool:
    if not distances:
        return False
    return distances[0] <= config.RELEVANCE_DISTANCE_THRESHOLD


def _looks_like_fact_query(message: str) -> bool:
    keywords = ["coupon", "discount", "offer", "contact", "phone", "email",
                "whatsapp", "hours", "timing", "open", "address",
                "कूपन", "छूट", "संपर्क", "समय"]
    lowered = message.lower()
    return any(k in lowered for k in keywords)


def handle_chat(tenant_id: str, session_id: str, message: str, site_name: str) -> Dict:
    # 1. Retrieve relevant chunks scoped strictly to this tenant
    raw = vector_query(tenant_id, message, n_results=config.TOP_K_RETRIEVAL)
    documents = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0]

    relevant = _is_relevant(distances)

    # 2. Always check manual facts (coupons/contact/etc.) regardless of
    #    vector relevance score, since these queries are short and may not
    #    embed close to crawled text.
    manual_facts = db.get_manual_facts(tenant_id)
    inject_manual_facts = _looks_like_fact_query(message) and manual_facts

    if not relevant and not inject_manual_facts:
        db.append_message(tenant_id, session_id, "user", message)
        db.append_message(tenant_id, session_id, "assistant", config.FALLBACK_MESSAGE)
        return {
            "reply": config.FALLBACK_MESSAGE,
            "products": [],
            "is_fallback": True,
        }

    # 3. Build context chunks for the LLM
    context_chunks = [{"text": doc} for doc in documents[: config.TOP_K_FINAL + 2]]
    if inject_manual_facts:
        for fact in manual_facts:
            context_chunks.append({"text": f"[{fact['fact_type'].upper()}] {fact['content']}"})

    history = db.get_recent_messages(tenant_id, session_id, limit=6)

    reply_text = llm.generate_reply(
        site_name=site_name,
        context_chunks=context_chunks,
        conversation_history=history,
        user_message=message,
    )

    # 4. Build structured product cards directly from metadata (not from
    #    LLM-generated text) so URLs/prices shown in the widget are always
    #    exactly what's in the database.
    products = []
    for meta in metadatas[: config.TOP_K_FINAL]:
        if meta.get("type") == "product":
            products.append({
                "name": meta.get("name", ""),
                "price": meta.get("price", ""),
                "url": meta.get("url", ""),
                "image": meta.get("image", ""),
                "stock_status": meta.get("stock_status", ""),
            })

    db.append_message(tenant_id, session_id, "user", message)
    db.append_message(tenant_id, session_id, "assistant", reply_text)

    return {
        "reply": reply_text,
        "products": products,
        "is_fallback": False,
    }
