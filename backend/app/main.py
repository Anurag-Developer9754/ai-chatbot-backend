"""
Main FastAPI application.

Endpoints:
  POST /api/v1/chat              - chat message from a WP plugin widget
  POST /api/v1/sync               - trigger WooCommerce + page crawl sync
  POST /api/v1/tenants             - admin: create a new tenant
  POST /api/v1/tenants/{id}/facts  - admin: add manual fact (coupon/contact/etc.)
  GET  /api/v1/tenants/{id}/status - admin: usage/status check
  GET  /health                     - health check
"""
import secrets
import logging
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ChatRequest, ChatResponse, ProductCard,
    SyncRequest, ManualFact, TenantConfig,
)
from . import db, rag, crawler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot-backend")

app = FastAPI(title="Site Chatbot Backend", version="1.0.0")

# In production, restrict allow_origins to your clients' actual domains
# instead of "*" once you know them, to reduce abuse risk.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    db.init_db()
    logger.info("Database initialized.")


@app.get("/health")
def health():
    return {"status": "ok"}


def _authenticate(tenant_id: str, x_api_token: str):
    if not db.verify_token(tenant_id, x_api_token or ""):
        raise HTTPException(status_code=401, detail="Invalid tenant_id or API token.")


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_api_token: str = Header(default="")):
    _authenticate(req.tenant_id, x_api_token)

    tenant = db.get_tenant(req.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Unknown tenant.")

    if not db.increment_and_check_usage(req.tenant_id):
        return ChatResponse(
            reply="Our chat assistant has reached its message limit for this month. "
                  "Please reach out to support directly, or check back next month.",
            products=[],
            is_fallback=True,
        )

    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")

    result = rag.handle_chat(
        tenant_id=req.tenant_id,
        session_id=req.session_id,
        message=req.message.strip(),
        site_name=tenant["site_url"],
    )

    return ChatResponse(
        reply=result["reply"],
        products=[ProductCard(**p) for p in result["products"]],
        is_fallback=result["is_fallback"],
    )


@app.post("/api/v1/sync")
def sync(req: SyncRequest, x_api_token: str = Header(default="")):
    _authenticate(req.tenant_id, x_api_token)

    products_indexed = 0
    categories_indexed = 0
    page_result = {"pages_indexed": 0, "failed_urls": []}

    try:
        if req.platform == "woocommerce":
            if not req.wc_consumer_key or not req.wc_consumer_secret:
                raise HTTPException(
                    status_code=400,
                    detail="WooCommerce consumer_key and consumer_secret are required.",
                )
            products_indexed = crawler.sync_woocommerce_products(
                req.tenant_id, req.site_url, req.wc_consumer_key, req.wc_consumer_secret
            )
            categories_indexed = crawler.sync_woocommerce_categories(
                req.tenant_id, req.site_url, req.wc_consumer_key, req.wc_consumer_secret
            )

        if req.crawl_pages:
            page_result = crawler.crawl_site_pages(req.tenant_id, req.site_url)

    except Exception as e:
        logger.exception("Sync failed for tenant %s", req.tenant_id)
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

    return {
        "tenant_id": req.tenant_id,
        "status": "completed",
        "products_indexed": products_indexed,
        "categories_indexed": categories_indexed,
        "pages_indexed": page_result["pages_indexed"],
        "failed_urls": page_result["failed_urls"],
    }


@app.post("/api/v1/tenants")
def create_tenant(cfg: TenantConfig):
    """Admin-only in practice — put this behind your own admin auth
    before exposing publicly. Returns the generated API token ONCE."""
    api_token = secrets.token_urlsafe(32)
    db.create_tenant(
        tenant_id=cfg.tenant_id,
        site_url=cfg.site_url,
        api_token=api_token,
        plan_tier=cfg.plan_tier,
        monthly_message_limit=cfg.monthly_message_limit,
    )
    return {"tenant_id": cfg.tenant_id, "api_token": api_token}


@app.post("/api/v1/tenants/{tenant_id}/facts")
def add_fact(tenant_id: str, fact: ManualFact, x_api_token: str = Header(default="")):
    _authenticate(tenant_id, x_api_token)
    db.add_manual_fact(tenant_id, fact.fact_type, fact.content)
    return {"status": "added"}


@app.get("/api/v1/tenants/{tenant_id}/status")
def tenant_status(tenant_id: str, x_api_token: str = Header(default="")):
    _authenticate(tenant_id, x_api_token)
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Unknown tenant.")
    return dict(tenant)
