"""Telegram channel crawler via RSSHub."""
import re
import json
import urllib.request
import ssl
import certifi
from typing import List, Dict, Any

from .base import BaseCrawler

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


class TelegramCrawler(BaseCrawler):
    """Crawl Telegram channels via RSSHub /telegram/channel/<username>."""

    def fetch(self) -> List[Dict[str, Any]]:
        channel = self.config["channel"]
        url = f"{self.rsshub_base}/telegram/channel/{channel}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  ERROR TG {self.name}: {e}")
            return []

        from .rss import parse_rss_xml
        items = parse_rss_xml(raw)

        for it in items:
            desc = it.get("summary", "")
            images = it.get("images", [])

            # 提取商品链接
            links = re.findall(r'https?://[^\s)"<>]+', desc)

            # 构造 raw_content：包含图片 + 链接
            raw = {}
            if images:
                raw["images"] = images
            if links:
                raw["links"] = links
            if raw:
                it["raw_content"] = json.dumps(raw, ensure_ascii=False)

        if self.filters:
            items = [it for it in items if self.apply_filters(it["title"] + " " + it.get("summary", ""))]
        return items[:8]
