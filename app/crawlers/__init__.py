"""Crawler factory - creates the right crawler for each source type."""
from typing import Dict, Any
from .base import BaseCrawler
from .rss import RSSCrawler, RSSHubCrawler
from .github import GitHubTrendingCrawler
from .telegram import TelegramCrawler


def create_crawler(source_config: Dict[str, Any], rsshub_base: str = "https://rss.255202.xyz") -> BaseCrawler:
    source_type = source_config.get("type", "rss")
    if source_type == "rss":
        return RSSCrawler(source_config, rsshub_base)
    elif source_type == "rsshub":
        return RSSHubCrawler(source_config, rsshub_base)
    elif source_type == "github_trending":
        return GitHubTrendingCrawler(source_config, rsshub_base)
    elif source_type == "telegram":
        return TelegramCrawler(source_config, rsshub_base)
    else:
        raise ValueError(f"Unknown source type: {source_type}")
