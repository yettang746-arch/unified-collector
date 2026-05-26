"""Collector engine - orchestrates all crawlers and stores results."""
import json
import yaml
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

from .crawlers import create_crawler
from .db import get_session, Article


def _fetch_full_text(url: str, timeout: int = 10) -> str:
    """抓取RSS文章原文全文，返回纯文本（最多2000字）。失败返回空字符串。"""
    import subprocess
    import re
    try:
        result = subprocess.run(
            ["curl", "-sS", "-L", "-m", str(timeout),
             "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
             url],
            capture_output=True, text=True, timeout=timeout + 5
        )
        html = result.stdout
    except Exception:
        return ""
    if not html or len(html) < 200:
        return ""
    # 去掉 script/style/header/footer/nav/aside
    html = re.sub(r'<(script|style|header|footer|nav|aside)[^>]*>.*?</\\1>', '', html, flags=re.S|re.I)
    # 尝试找 <article> 或 main 或 content 区域
    content_html = ""
    m = re.search(
        r'<(?:article|main)[^>]*>(.*?)</(?:article|main)>',
        html, re.S | re.I
    )
    if m:
        content_html = m.group(1)
    if not content_html:
        # 尝试找 class 含 content/article/post/entry 的 div
        m = re.search(
            r'<div[^>]*class="[^"]*(?:content|article|post|entry)[^"]*"[^>]*>(.*?)</div>',
            html, re.S | re.I
        )
        if m and len(m.group(1)) > 500:
            content_html = m.group(1)
    if content_html:
        text = re.sub(r'<[^>]+>', ' ', content_html)
    else:
        text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:2000]


def load_config(config_path: str = None) -> Dict[str, Any]:
    import os
    if config_path is None:
        config_path = os.environ.get("SOURCES_CONFIG", "/app/config/sources.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_published_at(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def collect_all(config_path: str = None) -> Dict[str, Any]:
    import os
    if config_path is None:
        config_path = os.environ.get("SOURCES_CONFIG", "/app/config/sources.yaml")
    """Run all enabled crawlers and store results. Returns stats."""
    config = load_config(config_path)
    rsshub_base = config.get("rsshub", {}).get("base_url", "https://rss.255202.xyz")
    sources = [s for s in config.get("sources", []) if s.get("enabled", True)]

    stats = {"total_fetched": 0, "total_stored": 0, "errors": [], "by_source": {}}
    all_items = []

    # Parallel crawling - max 10 concurrent
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {}
        for src in sources:
            try:
                crawler = create_crawler(src, rsshub_base)
                future = pool.submit(crawler.fetch)
                futures[future] = src
            except Exception as e:
                stats["errors"].append({"source": src["name"], "error": str(e)})

        for future in as_completed(futures, timeout=120):
            src = futures[future]
            try:
                items = future.result()
                source_type = src.get("type", "rss")
                scope = src.get("scope", "uncategorized")
                category = src.get("category", "uncategorized")
                lang = src.get("lang", "en")
                stats["by_source"][src["name"]] = len(items)
                stats["total_fetched"] += len(items)

                for item in items:
                    item["_source_config"] = src
                    item["_source_type"] = source_type
                    item["_scope"] = scope
                    item["_category"] = category
                    item["_lang"] = lang
                all_items.extend(items)
                print(f"  ✅ {src['name']}: {len(items)} items")
            except Exception as e:
                stats["errors"].append({"source": src["name"], "error": str(e)})
                print(f"  ❌ {src['name']}: {e}")

    # Store to DB
    from .db import SessionLocal
    # 全链路统一北京时间（CST = UTC+8）
    cst = timezone(timedelta(hours=8))
    now = datetime.now(cst)
    stored = 0
    skipped = 0
    session = SessionLocal()
    try:
        for item in all_items:
            url = item.get("url", "").strip()
            if not url:
                continue
            # Skip if already exists (dedup by URL)
            exists = session.query(Article).filter(Article.url == url).first()
            if exists:
                skipped += 1
                continue

            src_cfg = item["_source_config"]
            source_type = item["_source_type"]

            # RSS文章抓原文；TG帖子的summary即全文，不需要
            full_text = ""
            if source_type == "rss":
                full_text = _fetch_full_text(url)

            article = Article(
                source=src_cfg["name"],
                source_type=item["_source_type"],
                scope=item["_scope"],
                category=item["_category"],
                title=item.get("title", "").strip(),
                url=url,
                summary=item.get("summary", "").strip()[:1000],
                full_text=full_text,
                tags=item.get("tags", ""),
                lang=item["_lang"],
                published_at=_parse_published_at(item.get("published_at", "")),
                fetched_at=now,
                raw_content=item.get("raw_content", ""),
            )
            session.add(article)
            stored += 1

        session.commit()
        stats["total_stored"] = stored
        stats["total_skipped"] = skipped
    except Exception as e:
        session.rollback()
        stats["errors"].append({"phase": "storage", "error": str(e)})
        print(f"  ❌ Storage error: {e}")
    finally:
        session.close()

    print(f"\n📊 Total fetched: {stats['total_fetched']}, stored: {stored}, errors: {len(stats['errors'])}")
    return stats
