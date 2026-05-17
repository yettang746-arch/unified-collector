"""RSS crawler - handles both direct RSS feeds and RSSHub-proxied feeds."""
import re
import urllib.request
import ssl
import certifi
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Dict, Any

from .base import BaseCrawler

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _get_text(el):
    return el.text.strip() if el is not None and el.text else ""


def _get_link(el):
    if el is None:
        return ""
    href = el.get("href")
    if href:
        return href.strip()
    return el.text.strip() if el.text else ""


def _clean_ampersands(xml_str: str) -> str:
    return re.sub(r'&([a-zA-Z][a-zA-Z0-9]*)(?!;)', r'&amp;\1', xml_str)


def parse_rss_xml(raw: str) -> List[Dict[str, Any]]:
    """Parse RSS 2.0 or Atom feed XML into normalized items."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(_clean_ampersands(raw))
        except ET.ParseError:
            return []

    items = []
    # RSS 2.0
    for item in root.findall(".//item"):
        t = _get_text(item.find("title"))
        l = _get_text(item.find("link"))
        d_el = item.find("description")
        d_raw = (d_el.text or "") if d_el is not None else ""
        d = re.sub(r"<[^>]+>", "", d_raw).strip()[:500]
        # 提取图片 URL
        images = re.findall(r'<img[^>]+src=["\']([^"\'>]+)["\']', d_raw)
        p = _get_text(item.find("pubDate"))
        if t and l:
            item_dict = {"title": t, "url": l, "summary": d, "published_at": p}
            if images:
                item_dict["images"] = images
            items.append(item_dict)

    # Atom
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            t = _get_text(entry.find("atom:title", ns))
            l_el = entry.find('atom:link[@rel="alternate"]', ns) or entry.find("atom:link", ns)
            l = _get_link(l_el)
            d_el = entry.find("atom:summary", ns) or entry.find("atom:content", ns)
            d_raw = (d_el.text or "") if d_el is not None else ""
            d = re.sub(r"<[^>]+>", "", d_raw).strip()[:500]
            images = re.findall(r'<img[^>]+src=["\']([^"\'>]+)["\']', d_raw)
            p_el = entry.find("atom:published", ns) or entry.find("atom:updated", ns)
            p = _get_text(p_el)
            if t and l:
                item_dict = {"title": t, "url": l, "summary": d, "published_at": p}
                if images:
                    item_dict["images"] = images
                items.append(item_dict)

    return items


class RSSCrawler(BaseCrawler):
    """Crawler for direct RSS feeds."""

    def fetch(self) -> List[Dict[str, Any]]:
        url = self.config["url"]
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  ERROR RSS {self.name}: {e}")
            return []

        items = parse_rss_xml(raw)
        # Apply keyword filters
        if self.filters:
            items = [it for it in items if self.apply_filters(it["title"] + " " + it.get("summary", ""))]
        return items[:10]


class RSSHubCrawler(BaseCrawler):
    """Crawler for RSSHub-proxied feeds (e.g. HuggingFace Blog)."""

    def fetch(self) -> List[Dict[str, Any]]:
        route = self.config["route"]
        url = f"{self.rsshub_base}{route}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  ERROR RSSHub {self.name}: {e}")
            return []

        items = parse_rss_xml(raw)
        if self.filters:
            items = [it for it in items if self.apply_filters(it["title"] + " " + it.get("summary", ""))]
        return items[:10]
