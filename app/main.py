"""Unified Collector API - FastAPI entry point."""
import os
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .api.v1.articles import router as articles_router
from .collector import collect_all, load_config

API_KEY = os.environ.get("API_KEY", "")

app = FastAPI(
    title="Unified Collector",
    description="统一采集服务 - RSS/RSSHub/Telegram/GitHub Trending",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    print("✅ Database initialized")


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/v1/collect")
def trigger_collect(authorization: str = Header(None)):
    """手动触发采集（也可由 cron 调用）。"""
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Unauthorized")
    print("🚀 Starting collection...")
    stats = collect_all()
    return stats


@app.get("/api/v1/config")
def get_config(authorization: str = Header(None)):
    """返回当前数据源配置概览（不含敏感信息）。"""
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Unauthorized")
    config = load_config()
    sources = []
    for s in config.get("sources", []):
        sources.append({
            "name": s["name"],
            "type": s.get("type", ""),
            "scope": s.get("scope", ""),
            "category": s.get("category", ""),
            "enabled": s.get("enabled", True),
        })
    return {
        "total_sources": len(sources),
        "enabled_sources": len([s for s in sources if s["enabled"]]),
        "scope_labels": config.get("scope_labels", {}),
        "category_labels": config.get("category_labels", {}),
        "sources": sources,
    }


app.include_router(articles_router)
