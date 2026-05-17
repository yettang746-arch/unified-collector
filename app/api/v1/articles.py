"""API v1 routes - articles. 全链路统一北京时间 (CST = UTC+8)。"""
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import func
from typing import Optional

from ...db import get_session, Article

API_KEY = os.environ.get("API_KEY", "")


def _check_auth(authorization: str = Header(None)):
    """统一鉴权。"""
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "Unauthorized")


router = APIRouter(prefix="/api/v1", tags=["articles"])

# 全局统一：北京时间
CST = timezone(timedelta(hours=8))


def _article_to_dict(a: Article) -> dict:
    return {
        "id": a.id,
        "source": a.source,
        "source_type": a.source_type,
        "scope": a.scope,
        "category": a.category,
        "title": a.title,
        "url": a.url,
        "summary": a.summary or "",
        "raw_content": a.raw_content or "",
        "tags": a.tags or "",
        "lang": a.lang or "en",
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
    }


def _date_range_cst(date_str: str):
    """将 'YYYY-MM-DD' 转为 CST 当天的起止 datetime，用于 DB 查询。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = datetime(d.year, d.month, d.day, tzinfo=CST)
    end = start + timedelta(days=1)
    return start, end


@router.get("/articles")
def list_articles(
    date: Optional[str] = Query(None, description="按北京时间日期过滤 YYYY-MM-DD"),
    scope: Optional[str] = Query(None, description="一级分类: tech | cross-border | russia | selection"),
    category: Optional[str] = Query(None, description="二级分类（需配合 scope 使用）"),
    source: Optional[str] = Query(None, description="按来源名称过滤"),
    source_type: Optional[str] = Query(None, description="按来源类型: rss | rsshub | github_trending | telegram"),
    lang: Optional[str] = Query(None, description="按语言: zh | en | ru"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session=Depends(get_session),
):
    """查询文章列表。所有时间均为北京时间 (CST/UTC+8)。"""
    q = session.query(Article)
    if date:
        try:
            start, end = _date_range_cst(date)
            q = q.filter(Article.fetched_at >= start, Article.fetched_at < end)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    if scope:
        q = q.filter(Article.scope == scope)
    if category:
        q = q.filter(Article.category == category)
    if source:
        q = q.filter(Article.source == source)
    if source_type:
        q = q.filter(Article.source_type == source_type)
    if lang:
        q = q.filter(Article.lang == lang)

    total = q.count()
    articles = q.order_by(Article.fetched_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "scope": scope,
        "category": category,
        "articles": [_article_to_dict(a) for a in articles],
    }


@router.get("/articles/stats")
def article_stats(
    date: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    session=Depends(get_session),
):
    """采集统计（北京时间）。"""
    q = session.query(Article)
    if date:
        try:
            start, end = _date_range_cst(date)
            q = q.filter(Article.fetched_at >= start, Article.fetched_at < end)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    else:
        # 默认取最近24小时（CST）
        q = q.filter(Article.fetched_at >= datetime.now(CST) - timedelta(days=1))
    if scope:
        q = q.filter(Article.scope == scope)

    results = q.with_entities(
        Article.scope, Article.source, Article.category, func.count(Article.id)
    ).group_by(Article.scope, Article.source, Article.category).all()

    by_scope = {}
    by_source = {}
    by_category = {}
    total = 0
    for scope_val, source, category, cnt in results:
        by_scope[scope_val] = by_scope.get(scope_val, 0) + cnt
        by_source[source] = by_source.get(source, 0) + cnt
        by_category[category] = by_category.get(category, 0) + cnt
        total += cnt

    return {
        "total": total,
        "by_scope": by_scope,
        "by_source": by_source,
        "by_category": by_category,
    }



