"""
Groq chat-completion wrapper.

Strictness is enforced at TWO layers (the prompt is layer 2 — layer 1
is the retrieval-confidence gate in rag.py which can skip the LLM call
entirely if nothing relevant was found).
"""
from typing import List, Dict
from groq import Groq

from . import config

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your environment / .env file."
            )
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


SYSTEM_PROMPT_TEMPLATE = """You are a customer support assistant for an e-commerce website ({site_name}).

STRICT RULES (do not break these under any circumstance):
1. Answer ONLY using the CONTEXT provided below. Never use outside knowledge.
2. If the answer is not in the CONTEXT, say exactly: "I don't have that exact information right now — let me connect you with our support team." Do not guess.
3. Never invent prices, stock status, coupon codes, phone numbers, or links. Only use values that literally appear in CONTEXT.
4. If the user asks about anything unrelated to this website (general knowledge, news, other topics), politely decline and say you can only help with this website's products and services.
5. Reply in the same language/style the user used (English, Hindi, or Hinglish).
6. Keep replies concise and natural, like a helpful store employee — not a robot reading a list.
7. When recommending products, mention only products that appear in CONTEXT, and never alter their listed price or URL.

CONTEXT:
{context}
"""


def build_context_block(chunks: List[Dict]) -> str:
    """Turn retrieved chunks into a clean text block for the prompt."""
    if not chunks:
        return "(no relevant information found)"
    lines = []
    for c in chunks:
        lines.append(f"- {c['text']}")
    return "\n".join(lines)


def generate_reply(
    site_name: str,
    context_chunks: List[Dict],
    conversation_history: List[Dict[str, str]],
    user_message: str,
) -> str:
    """
    conversation_history: list of {"role": "user"|"assistant", "content": str}
    for short-term session memory (point #7 in the requirements doc).
    """
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        site_name=site_name,
        context=build_context_block(context_chunks),
    )

    messages = [{"role": "system", "content": system_prompt}]
    # keep memory bounded — last 6 turns is plenty for follow-up context
    messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})

    client = get_client()
    completion = client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=messages,
        temperature=0.3,  # low temperature -> fewer creative deviations from context
        max_tokens=500,
    )
    return completion.choices[0].message.content.strip()
