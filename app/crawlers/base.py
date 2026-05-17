"""Base crawler interface."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseCrawler(ABC):
    """Base class for all crawlers."""

    def __init__(self, source_config: Dict[str, Any], rsshub_base: str = ""):
        self.config = source_config
        self.name = source_config["name"]
        self.category = source_config.get("category", "uncategorized")
        self.lang = source_config.get("lang", "en")
        self.rsshub_base = rsshub_base
        self.filters = source_config.get("filters", [])

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch articles. Returns list of dicts with keys:
        title, url, summary, published_at, raw_content
        """
        pass

    def apply_filters(self, text: str) -> bool:
        """Check if text matches any filter keyword. Returns True if passes."""
        if not self.filters:
            return True
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.filters)
