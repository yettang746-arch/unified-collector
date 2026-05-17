"""Collector engine - orchestrates all crawlers and stores results."""
import json
import yaml
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

from .crawlers import create_crawler
from .db import get_session, Article


def load_config(config_path: str = "/app/config/sources.yaml") -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_published_at(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def collect_all(config_path: str = "/app/config/sources.yaml") -> Dict[str, Any]:
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
            article = Article(
                source=src_cfg["name"],
                source_type=item["_source_type"],
                scope=item["_scope"],
                category=item["_category"],
                title=item.get("title", "").strip(),
                url=url,
                summary=item.get("summary", "").strip()[:1000],
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
