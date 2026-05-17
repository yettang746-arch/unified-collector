#!/usr/bin/env python3
"""
统一采集拉取脚本 - 全链路北京时间
下游按 scope 拉数据，互不干扰。

用法：
  python3 pull-from-collector.py --scope tech          → 晨报素材
  python3 pull-from-collector.py --scope russia        → 俄罗斯市场晨报
  python3 pull-from-collector.py --scope selection     → 选品参考
  python3 pull-from-collector.py --scope cross-border  → 跨境日报
  python3 pull-from-collector.py --all                 → 全部（调试用）
"""
import argparse
import json
import os
import urllib.request
import ssl
from datetime import datetime, timezone, timedelta

API_URL = os.environ.get("COLLECTOR_URL", "https://collector.255202.xyz")
API_KEY = os.environ.get("API_KEY", "cbtc_2026_k3y")

# 全链路统一北京时间
CST = timezone(timedelta(hours=8))

# 输出目录映射
SCOPE_DIRS = {
    "tech": "/Users/zijun/.openclaw/workspace-team/daily-article/inbox",
    "russia": "/Users/zijun/.openclaw/workspace-team/daily-article/russian-market/inbox",
    "selection": "/Users/zijun/.openclaw/workspace-team/daily-article/russian-market/inbox",
    "cross-border": "/Users/zijun/.openclaw/workspace-team/daily-article/inbox",
}

CATEGORY_LABELS = {
    "ai-frontier": "AI前沿",
    "dev-daily": "开发者日报",
    "tech-industry": "科技产业",
    "industry": "跨境电商行业动态",
    "tools": "电商工具/平台更新",
    "news": "俄语热点",
    "economy": "俄罗斯经济",
    "business": "商业财经",
    "politics": "政治外交",
    "retail": "俄罗斯零售",
    "fashion": "时尚选品",
    "home": "家居百货选品",
    "deals": "折扣促销",
    "gadgets": "好物推荐",
    "wb-recommend": "WB好物推荐",
    "wb-fashion": "WB时尚穿搭",
    "wb-home": "WB家居装饰",
    "wb-deals": "WB折扣优惠",
}


def fetch_articles(scope: str, date_str: str) -> list:
    url = f"{API_URL}/api/v1/articles?scope={scope}&date={date_str}&limit=500"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "User-Agent": "curl/8.0.0"
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        data = json.loads(resp.read())
    return data.get("articles", [])


def build_inbox_md(articles: list, scope: str, date_str: str) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    by_cat = {}
    for a in articles:
        cat = a.get("category", "other")
        by_cat.setdefault(cat, []).append(a)

    lines = [f"## 素材包 · {scope} · {date_str} {now}", ""]

    cat_order = list(CATEGORY_LABELS.keys())
    for cat in cat_order:
        if cat not in by_cat:
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        lines.append(f"### {label}")
        lines.append("")
        for a in by_cat[cat][:10]:
            title = a.get("title", "").strip()
            summary = (a.get("summary") or "").strip()[:150]
            url = a.get("url", "").strip()
            source = a.get("source", "")
            lang = a.get("lang", "")
            flag = {"ru": "🇷🇺", "zh": "🇨🇳", "en": "🇬🇧"}.get(lang, "")

            lines.append(f"- {flag} **{title}**")
            if source:
                lines.append(f"  来源：{source}")
            if summary:
                lines.append(f"  摘要：{summary}")
            if url:
                lines.append(f"  链接：{url}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).strip()


def build_selection_json(articles: list) -> list:
    import re
    results = []
    for a in articles:
        desc = a.get("summary", "")
        links = re.findall(r'https?://[^\s)"<>]+', desc)
        url = a.get("url", "")
        if url and url not in links:
            links.insert(0, url)
        tags = re.findall(r'#\w+', desc)
        results.append({
            "source": a.get("source", ""),
            "category": a.get("category", ""),
            "title": a.get("title", ""),
            "desc": desc,
            "link": url,
            "links": links,
            "tags": list(set(tags)),
            "pub": a.get("published_at", ""),
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="从统一采集服务拉取数据（全链路北京时间）")
    parser.add_argument("--scope", choices=["tech", "russia", "selection", "cross-border"],
                        help="拉取哪个 scope 的数据")
    parser.add_argument("--all", action="store_true", help="拉取所有 scope")
    args = parser.parse_args()

    scopes = ["tech", "cross-border", "russia", "selection"] if args.all else [args.scope]

    # 统一用北京时间日期
    today = datetime.now(CST).strftime("%Y-%m-%d")

    for scope in scopes:
        if not scope:
            continue
        print(f"\n{'='*50}")
        print(f"📡 Pulling scope={scope}, date={today} (CST)")
        articles = fetch_articles(scope, today)
        print(f"  Got {len(articles)} articles")

        if not articles:
            print(f"  ⏭️ No articles for {scope}")
            continue

        out_dir = SCOPE_DIRS.get(scope, "/tmp")
        os.makedirs(out_dir, exist_ok=True)

        if scope == "tech":
            md_path = os.path.join(out_dir, f"{today}.md")
        else:
            md_path = os.path.join(out_dir, f"{today}_{scope}.md")

        if scope == "tech" and os.path.exists(md_path):
            content = build_inbox_md(articles, scope, today)
            with open(md_path, "a", encoding="utf-8") as f:
                f.write("\n\n" + content + "\n")
        else:
            content = build_inbox_md(articles, scope, today)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content + "\n")

        print(f"  ✅ Written {len(content)} bytes → {md_path}")

        if scope == "selection":
            sel_data = build_selection_json(articles)
            json_path = os.path.join(out_dir, f"{today}_selection.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(sel_data, f, ensure_ascii=False, indent=2)
            print(f"  📦 Selection JSON: {len(sel_data)} items → {json_path}")


if __name__ == "__main__":
    main()
