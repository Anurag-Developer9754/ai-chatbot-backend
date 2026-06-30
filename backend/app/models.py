"""
Pydantic request/response models for the multi-tenant chatbot backend.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    tenant_id: str
    session_id: str
    message: str
    language: Optional[Literal["en", "hi", "hinglish", "auto"]] = "auto"


class ProductCard(BaseModel):
    name: str
    price: Optional[str] = None
    url: str
    image: Optional[str] = None
    stock_status: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    products: List[ProductCard] = Field(default_factory=list)
    is_fallback: bool = False
    lead_capture_triggered: bool = False


class SyncRequest(BaseModel):
    tenant_id: str
    site_url: str
    platform: Literal["wordpress", "woocommerce"] = "woocommerce"
    wc_consumer_key: Optional[str] = None
    wc_consumer_secret: Optional[str] = None
    crawl_pages: bool = True  # also crawl FAQ/policy/about/contact pages


class SyncStatus(BaseModel):
    tenant_id: str
    status: Literal["running", "completed", "failed"]
    products_indexed: int = 0
    pages_indexed: int = 0
    failed_urls: List[str] = Field(default_factory=list)


class ManualFact(BaseModel):
    """Admin-entered high-priority facts (coupons, contact, hours) that
    bypass the crawler and are always injected into context when relevant."""
    tenant_id: str
    fact_type: Literal["coupon", "contact", "store_hours", "policy", "other"]
    content: str  # free text, e.g. "Code SAVE20: 20% off on orders above ₹999"


class TenantConfig(BaseModel):
    tenant_id: str
    site_url: str
    plan_tier: Literal["trial", "basic", "pro"] = "trial"
    monthly_message_limit: int = 500
    bot_name: str = "Assistant"
    widget_color: str = "#1a73e8"
    welcome_message: str = "Hi! How can I help you today?"
