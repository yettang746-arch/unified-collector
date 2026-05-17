"""API v1 routes - sources management. 远程热更新数据源配置。"""
import os
import yaml
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional, List
from pydantic import BaseModel

from ...db import get_session

router = APIRouter(prefix="/api/v1", tags=["sources"])

CONFIG_PATH = os.environ.get("SOURCES_CONFIG", "/app/config/sources.yaml")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


@router.get("/sources")
def list_sources():
    """列出所有数据源配置。"""
    config = _load_config()
    sources = config.get("sources", [])
    return {
        "total": len(sources),
        "enabled": len([s for s in sources if s.get("enabled", True)]),
        "sources": sources,
    }


class SourceItem(BaseModel):
    name: str
    type: str  # rss | rsshub | github_trending | telegram
    scope: str
    category: str
    lang: str = "en"
    enabled: bool = True
    # RSS
    url: Optional[str] = None
    # RSSHub
    route: Optional[str] = None
    # GitHub Trending
    language: Optional[str] = None
    # Telegram
    channel: Optional[str] = None
    # 通用
    filters: Optional[List[str]] = None


@router.post("/sources")
def add_source(source: SourceItem, authorization: str = Header(None)):
    """远程新增数据源（热更新，无需重启）。"""
    from .articles import _check_auth
    _check_auth(authorization)

    config = _load_config()
    sources = config.get("sources", [])

    # 检查重名
    if any(s["name"] == source.name for s in sources):
        raise HTTPException(409, f"Source '{source.name}' already exists")

    new_source = {k: v for k, v in source.dict().items() if v is not None}
    sources.append(new_source)
    config["sources"] = sources
    _save_config(config)

    return {"ok": True, "action": "added", "source": new_source}


@router.put("/sources/{source_name}")
def update_source(source_name: str, source: SourceItem, authorization: str = Header(None)):
    """远程更新数据源（热更新，无需重启）。"""
    from .articles import _check_auth
    _check_auth(authorization)

    config = _load_config()
    sources = config.get("sources", [])

    idx = None
    for i, s in enumerate(sources):
        if s["name"] == source_name:
            idx = i
            break

    new_source = {k: v for k, v in source.dict().items() if v is not None}
    if idx is not None:
        sources[idx] = new_source
        action = "updated"
    else:
        sources.append(new_source)
        action = "added"

    config["sources"] = sources
    _save_config(config)

    return {"ok": True, "action": action, "source": new_source}


@router.delete("/sources/{source_name}")
def delete_source(source_name: str, authorization: str = Header(None)):
    """远程删除数据源（热更新，无需重启）。"""
    from .articles import _check_auth
    _check_auth(authorization)

    config = _load_config()
    sources = config.get("sources", [])
    new_sources = [s for s in sources if s["name"] != source_name]

    if len(new_sources) == len(sources):
        raise HTTPException(404, f"Source '{source_name}' not found")

    config["sources"] = new_sources
    _save_config(config)

    return {"ok": True, "action": "deleted", "name": source_name}


@router.post("/sources/reload")
def reload_sources(authorization: str = Header(None)):
    """强制重新加载配置文件（通常不需要，因为每次请求都会重新读取）。"""
    from .articles import _check_auth
    _check_auth(authorization)

    config = _load_config()
    sources = config.get("sources", [])
    return {
        "ok": True,
        "total": len(sources),
        "enabled": len([s for s in sources if s.get("enabled", True)]),
    }
