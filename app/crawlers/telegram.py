"""Telegram channel crawler via RSSHub."""
import re
import json
import html as _html
import urllib.request
import ssl
import certifi
from typing import List, Dict, Any

from .base import BaseCrawler

SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _parse_products_from_html(d_raw: str) -> list:
    """从 RSSHub 返回的 Telegram description HTML 中提取商品列表，做图文配对。

    RSSHub 格式：<p>商品描述+链接</p><img src="..."> 交替出现。
    配对策略：按 <img> 标签分段，每个 <p> 块是一个商品，紧跟的 <img> 是它的图片。
    如果没有 <img>，所有图片挂在第一个商品上。
    """
    decoded = _html.unescape(d_raw)

    # 提取所有 <img> 及其位置
    img_pattern = re.compile(r'<img[^>]+src=["\']([^"\'>]+)["\'][^>]*>')
    img_matches = list(img_pattern.finditer(decoded))

    # 按 <img> 标签把 HTML 分成段
    parts = img_pattern.split(decoded)
    # split 后: [text_block, img_url, text_block, img_url, ...]
    # 重新组织为 [(text_block, [img_urls])] 的列表

    if not img_matches:
        # 没有图片，整体作为一个商品
        text = re.sub(r'<[^>]+>', '', decoded).strip()
        links = re.findall(r'https?://[^\s)"<>]+', text)
        return [{"text": text, "images": [], "links": links}]

    products = []
    # parts[0] = 第一个 img 前的文本
    # parts[1] = 第一个 img 的 URL（由 split 捕获组产生）
    # parts[2] = 第一个和第二个 img 之间的文本
    # ...
    # 结构: [text0, img_url0, text1, img_url1, text2, ...]

    # 将 parts 重新组织
    # 每个 segment: 前面紧挨着的 text + img_url
    text_blocks = []
    img_urls = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            text_blocks.append(part)
        else:
            img_urls.append(part)

    # 配对：text_blocks[i] 对应 img_urls[i-1]（图片在文本块之后）
    # 但实际 HTML 结构是 <p>text</p><img>，所以 text_block[i] 的图片是 img_urls[i]
    # 特殊情况：最后一个 text_block 可能没有对应图片

    for i, text_html in enumerate(text_blocks):
        if not text_html.strip():
            continue
        text = re.sub(r'<[^>]+>', '', text_html).strip()
        if not text:
            continue

        # 这个文本块对应的图片：img_urls[i]（如果有）
        product_images = []
        if i < len(img_urls) and img_urls[i]:
            product_images.append(img_urls[i])

        links = re.findall(r'https?://[^\s)"<>]+', text)
        products.append({
            "text": text[:500],
            "images": product_images,
            "links": links,
        })

    # 如果配对结果只有图片没有文本（极端情况），退回到扁平模式
    if not products:
        all_images = [m.group(1) for m in img_matches]
        text = re.sub(r'<[^>]+>', '', decoded).strip()
        links = re.findall(r'https?://[^\s)"<>]+', text)
        products.append({"text": text, "images": all_images, "links": links})

    return products


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
            # 用 RSS 2.0 解析后的 summary（已解码），但我们需要原始 HTML 做图文配对
            # parse_rss_xml 已做了 html.unescape，summary 是纯文本，images 是提取的图片列表
            summary = it.get("summary", "")
            images = it.get("images", [])

            # 提取商品链接
            links = re.findall(r'https?://[^\s)"<>]+', summary)

            # 构造 raw_content：图文配对后的商品列表
            if images:
                # 多图场景：尝试图文配对
                if len(images) == 1:
                    # 单图：直接绑定
                    raw_content = json.dumps({
                        "products": [{"text": summary, "images": images, "links": links}],
                        "images": images,
                        "links": links,
                    }, ensure_ascii=False)
                else:
                    # 多图：图片按顺序和文本段落配对
                    # 简化策略：第一张图绑定，其余作为附加图
                    products = []
                    product_links = links[:1] if links else []
                    product_images = [images[0]] if images else []

                    # 将 summary 按链接分段（如果多个链接说明多个商品）
                    if len(links) > 1:
                        for idx, link in enumerate(links):
                            img = images[idx] if idx < len(images) else ""
                            # 找 link 附近的文本
                            link_pos = summary.find(link)
                            if link_pos >= 0:
                                # 从上一个链接后到此链接后的文本
                                end_pos = link_pos + len(link)
                                # 简化：取 link 前 100 字 + link 本身
                                start = max(0, link_pos - 100)
                                seg_text = summary[start:end_pos].strip()
                            else:
                                seg_text = link
                            products.append({
                                "text": seg_text,
                                "images": [img] if img else [],
                                "links": [link],
                            })
                    else:
                        # 单链接多图：所有图绑到同一个商品
                        products.append({
                            "text": summary,
                            "images": images,
                            "links": links,
                        })

                    raw_content = json.dumps({
                        "products": products,
                        "images": images,
                        "links": links,
                    }, ensure_ascii=False)
            else:
                raw_content = json.dumps({
                    "images": [],
                    "links": links,
                }, ensure_ascii=False)

            it["raw_content"] = raw_content

        if self.filters:
            items = [it for it in items if self.apply_filters(it["title"] + " " + it.get("summary", ""))]
        return items[:8]
