"""
Central configuration. All secrets come from environment variables —
never hardcode the Groq API key here.
"""
import os
from pathlib import Path

# --- API Keys (set these in your .env / hosting environment) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Storage paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(BASE_DIR / "chroma_store"))
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "tenants.db"))

# --- Embedding model (local, free, no API cost) ---
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

# --- Retrieval tuning ---
# ChromaDB returns L2 distance by default (lower = more similar).
# Anything above this distance is treated as "not relevant enough" -> fallback.
RELEVANCE_DISTANCE_THRESHOLD = float(os.getenv("RELEVANCE_DISTANCE_THRESHOLD", "0.85"))
TOP_K_RETRIEVAL = int(os.getenv("TOP_K_RETRIEVAL", "8"))
TOP_K_FINAL = int(os.getenv("TOP_K_FINAL", "4"))  # how many products to actually surface

# --- Off-topic / fallback messages ---
FALLBACK_MESSAGE = (
    "Sorry, I can only assist with information related to this website, "
    "its products, and services. Would you like me to connect you with our support team?"
)

# --- Auth ---
# Simple per-tenant API token check (proxy auth from the WP plugin -> backend).
# In production, store hashed tokens in the tenant DB instead of plain compare.
REQUIRE_TENANT_TOKEN = os.getenv("REQUIRE_TENANT_TOKEN", "true").lower() == "true"

# --- Crawler ---
CRAWL_USER_AGENT = "Mozilla/5.0 (compatible; SiteChatbotCrawler/1.0)"
CRAWL_TIMEOUT_SECONDS = 15
MAX_PAGES_TO_CRAWL = int(os.getenv("MAX_PAGES_TO_CRAWL", "300"))
