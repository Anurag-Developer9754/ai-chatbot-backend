"""
Lightweight SQLite store for everything that ISN'T vector data:
tenant config, monthly usage counters, manually-entered facts
(coupons/contact/hours), and short-term chat session memory.

SQLite is sufficient at 2-3 client scale. Swap for Postgres later
without changing the calling code much (same function signatures).
"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import Optional, List, Dict

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    site_url TEXT NOT NULL,
    api_token TEXT NOT NULL,
    plan_tier TEXT DEFAULT 'trial',
    monthly_message_limit INTEGER DEFAULT 500,
    bot_name TEXT DEFAULT 'Assistant',
    widget_color TEXT DEFAULT '#1a73e8',
    welcome_message TEXT DEFAULT 'Hi! How can I help you today?',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS usage (
    tenant_id TEXT,
    year_month TEXT,
    message_count INTEGER DEFAULT 0,
    PRIMARY KEY (tenant_id, year_month)
);

CREATE TABLE IF NOT EXISTS manual_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT,
    fact_type TEXT,
    content TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT,
    tenant_id TEXT,
    role TEXT,
    content TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT,
    session_id TEXT,
    name TEXT,
    contact TEXT,
    query_summary TEXT,
    created_at REAL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- Tenants ----------

def create_tenant(tenant_id: str, site_url: str, api_token: str, plan_tier: str = "trial",
                   monthly_message_limit: int = 500):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tenants (tenant_id, site_url, api_token, plan_tier, "
            "monthly_message_limit, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, site_url, api_token, plan_tier, monthly_message_limit, time.time()),
        )


def get_tenant(tenant_id: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,))
        return cur.fetchone()


def verify_token(tenant_id: str, token: str) -> bool:
    tenant = get_tenant(tenant_id)
    if not tenant:
        return False
    return tenant["api_token"] == token


# ---------- Usage / quota ----------

def increment_and_check_usage(tenant_id: str) -> bool:
    """Returns True if the tenant is still within their monthly quota
    (and increments the counter). Returns False if quota exceeded
    (does NOT increment further once over limit)."""
    ym = time.strftime("%Y-%m")
    tenant = get_tenant(tenant_id)
    limit = tenant["monthly_message_limit"] if tenant else 500

    with get_conn() as conn:
        cur = conn.execute(
            "SELECT message_count FROM usage WHERE tenant_id=? AND year_month=?",
            (tenant_id, ym),
        )
        row = cur.fetchone()
        current = row["message_count"] if row else 0

        if current >= limit:
            return False

        if row:
            conn.execute(
                "UPDATE usage SET message_count = message_count + 1 WHERE tenant_id=? AND year_month=?",
                (tenant_id, ym),
            )
        else:
            conn.execute(
                "INSERT INTO usage (tenant_id, year_month, message_count) VALUES (?, ?, 1)",
                (tenant_id, ym),
            )
        return True


# ---------- Manual facts (coupons / contact / hours) ----------

def add_manual_fact(tenant_id: str, fact_type: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO manual_facts (tenant_id, fact_type, content, created_at) VALUES (?, ?, ?, ?)",
            (tenant_id, fact_type, content, time.time()),
        )


def get_manual_facts(tenant_id: str) -> List[Dict]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT fact_type, content FROM manual_facts WHERE tenant_id=?", (tenant_id,)
        )
        return [dict(r) for r in cur.fetchall()]


# ---------- Chat session memory ----------

def append_message(tenant_id: str, session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_sessions (session_id, tenant_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, tenant_id, role, content, time.time()),
        )


def get_recent_messages(tenant_id: str, session_id: str, limit: int = 6) -> List[Dict[str, str]]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT role, content FROM chat_sessions WHERE tenant_id=? AND session_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (tenant_id, session_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return list(reversed(rows))


# ---------- Leads ----------

def save_lead(tenant_id: str, session_id: str, name: str, contact: str, query_summary: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO leads (tenant_id, session_id, name, contact, query_summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, session_id, name, contact, query_summary, time.time()),
        )
