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


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx

def fetch_articles(scope: str, date_str: str) -> list:
    url = f"{API_URL}/api/v1/articles?scope={scope}&date={date_str}&limit=500"
    # Prefer curl (avoids Python SSL issues on some hosts)
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-sS", "-m", "30", "-H", f"Authorization: Bearer {API_KEY}", url],
            capture_output=True, text=True, timeout=35
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            return data.get("articles", [])
    except Exception:
        pass
    # Fallback to urllib
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "User-Agent": "curl/8.0.0"
    })
    ctx = _ssl_ctx()
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
            source_type = a.get("source_type", "")
            lang = a.get("lang", "")
            flag = {"ru": "🇷🇺", "zh": "🇨🇳", "en": "🇬🇧"}.get(lang, "")

            lines.append(f"- {flag} **{title}**")
            if source:
                lines.append(f"  来源：{source}")

            # 优先用API返回的full_text（VPS采集时已抓），没有则fallback到summary
            full_text = (a.get("full_text") or "").strip()
            summary = (a.get("summary") or "").strip()[:150]

            if full_text:
                lines.append(f"  原文：{full_text}")
            elif summary:
                lines.append(f"  摘要：{summary}")

            if url:
                lines.append(f"  链接：{url}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).strip()


def build_selection_json(articles: list, img_map: dict = None) -> list:
    import re
    results = []
    for idx, a in enumerate(articles):
        desc = a.get("summary", "")
        links = re.findall(r'https?://[^\s)"<>]+', desc)
        url = a.get("url", "")
        if url and url not in links:
            links.insert(0, url)
        tags = re.findall(r'#\w+', desc)
        # 提取远程图片
        remote_images = []
        raw_content = a.get("raw_content", "")
        if raw_content:
            try:
                rc = json.loads(raw_content)
                remote_images = rc.get("images", [])
            except Exception:
                pass
        local_imgs = img_map.get(idx, []) if img_map else []
        results.append({
            "source": a.get("source", ""),
            "category": a.get("category", ""),
            "title": a.get("title", ""),
            "desc": desc,
            "link": url,
            "links": links,
            "images": remote_images,
            "local_images": local_imgs,
            "tags": list(set(tags)),
            "pub": a.get("published_at", ""),
        })
    return results


def _download_image(url: str, save_path: str) -> bool:
    """下载图片到本地，返回是否成功。"""
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-sS", "-m", "5", "-o", save_path, url],
            capture_output=True, timeout=8
        )
        if result.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 100:
            return True
    except Exception:
        pass
    # Fallback to urllib
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = _ssl_ctx()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            if resp.status == 200:
                with open(save_path, "wb") as f:
                    f.write(resp.read())
                return True
    except Exception as e:
        print(f"    ⚠️ 下载失败 {url[:60]}...: {e}")
    return False


def _download_article_images(articles: list, img_dir: str) -> dict:
    """批量下载文章图片到指定目录（并发+总超时），返回 {article_index: [local_paths]}。"""
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    IMG_WORKERS = 10          # 并发数
    TOTAL_DEADLINE = 90       # 总超时（秒），防止无限卡住
    MAX_IMGS_PER_ITEM = 3     # 每条最多几张

    os.makedirs(img_dir, exist_ok=True)
    result = {}
    total = 0
    tasks = []  # (idx, img_url, save_path)

    for idx, a in enumerate(articles):
        images = []
        raw_content = a.get("raw_content", "")
        if raw_content:
            try:
                rc = json.loads(raw_content)
                images = rc.get("images", [])
            except Exception:
                pass
        if not images:
            continue
        src = a.get("source", "unknown").replace("/", "_").replace(" ", "_")[:30]
        for i, img_url in enumerate(images[:MAX_IMGS_PER_ITEM]):
            ext = ".jpg"
            if ".png" in img_url:
                ext = ".png"
            elif ".webp" in img_url:
                ext = ".webp"
            filename = f"{src}_{idx}_{i}{ext}"
            save_path = os.path.join(img_dir, filename)
            if os.path.exists(save_path):
                result.setdefault(idx, []).append(save_path)
            else:
                total += 1
                tasks.append((idx, img_url, save_path))

    if not tasks:
        existing = sum(len(v) for v in result.values())
        print(f"  📷 图片已全部存在 ({existing} 张)")
        return result

    print(f"  📷 下载 {len(tasks)} 张图片（并发 {IMG_WORKERS}，总超时 {TOTAL_DEADLINE}s）...")
    start = _time.monotonic()
    ok = 0
    fail = 0

    with ThreadPoolExecutor(max_workers=IMG_WORKERS) as pool:
        futures = {pool.submit(_download_image, url, path): (idx, path) for idx, url, path in tasks}
        for fut in list(futures):
            remaining = TOTAL_DEADLINE - (_time.monotonic() - start)
            if remaining <= 0:
                print(f"  ⚠️ 图片下载总超时，已处理 {ok+fail}/{len(tasks)}")
                pool.shutdown(wait=False, cancel_futures=True)
                break
            idx, path = futures[fut]
            try:
                success = fut.result(timeout=max(remaining, 1))
            except Exception:
                success = False
            if success:
                ok += 1
                result.setdefault(idx, []).append(path)
            else:
                fail += 1

    existing = sum(len(v) for v in result.values())
    print(f"  📷 图片: {ok} 新下载, {fail} 失败 | 总计: {existing} 张 → {img_dir}")
    return result


def build_ecom_products_md(articles: list, date_str: str, img_map: dict = None) -> str:
    """按 source 分组输出选品数据，兼容方远热卖好物初稿的输入格式。
    格式：# 标题 > ## 频道名 > ### [时间] 标题 + 描述 + 链接 + 本地图片
    """
    import re

    # 按 source 分组
    by_source = {}
    for a in articles:
        src = a.get("source", "unknown")
        by_source.setdefault(src, []).append(a)

    lines = [f"# 跨境电商选品参考 ({date_str})", ""]
    lines.append(f"> 共 {len(articles)} 条")
    if img_map:
        img_count = sum(len(v) for v in img_map.values())
        lines.append(f"> 📷 已下载 {img_count} 张素材图片")
    lines.append("")

    for src, items in by_source.items():
        lines.append(f"## {src}")
        lines.append("")
        for item_idx, a in enumerate(items):
            # 找到这篇文章在 articles 里的全局索引
            global_idx = None
            for gi, ga in enumerate(articles):
                if ga is a:
                    global_idx = gi
                    break

            title = a.get("title", "").strip()
            desc = a.get("summary", "").strip()
            pub = a.get("published_at", "")
            # 提取发布日期简写
            pub_short = ""
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub)
                    pub_short = dt.strftime("%a,")
                except Exception:
                    pass

            lines.append(f"### [{pub_short}] {title}")
            lines.append("")

            # 图片：优先用本地下载的，fallback 到远程 URL
            images = []
            raw_content = a.get("raw_content", "")
            if raw_content:
                try:
                    rc = json.loads(raw_content)
                    images = rc.get("images", [])
                except Exception:
                    pass

            local_imgs = img_map.get(global_idx, []) if img_map else []
            if local_imgs:
                for lp in local_imgs:
                    lines.append(f"![img]({lp})")
                lines.append("")
            elif images:
                for img in images[:3]:
                    lines.append(f"![img]({img})")
                lines.append("")

            if desc:
                lines.append(desc)
                lines.append("")

            # 提取链接
            links = re.findall(r'https?://[^\s)"<>]+', desc)
            url = a.get("url", "")
            if url and url not in links:
                links.insert(0, url)
            if links:
                lines.append("**链接:**")
                for lnk in links[:10]:
                    lines.append(f"- {lnk}")

            # 标签
            tags = re.findall(r'#\w+', desc)
            if tags:
                lines.append("")
                lines.append(f"标签: {' '.join(set(tags))}")

            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


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

        # russian-market inbox 按日期分目录
        if scope in ("russia", "selection"):
            day_dir = os.path.join(out_dir, today)
            os.makedirs(day_dir, exist_ok=True)
        else:
            day_dir = out_dir

        if scope == "tech":
            md_path = os.path.join(out_dir, f"{today}.md")
        elif scope == "russia":
            md_path = os.path.join(day_dir, "russia.md")
        else:
            md_path = os.path.join(day_dir, f"{today}_{scope}.md")

        if scope == "tech" and os.path.exists(md_path):
            content = build_inbox_md(articles, scope, today)
            with open(md_path, "a", encoding="utf-8") as f:
                f.write("\n\n" + content + "\n")
        else:
            content = build_inbox_md(articles, scope, today)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(content + "\n")

        if scope == "selection":
            # 选品：先下载图片，再用方远兼容格式输出
            img_dir = os.path.join(day_dir, "images")
            img_map = _download_article_images(articles, img_dir)

            ecom_content = build_ecom_products_md(articles, today, img_map)
            ecom_path = os.path.join(day_dir, f"{today}_ecom_products.md")
            with open(ecom_path, "w", encoding="utf-8") as f:
                f.write(ecom_content + "\n")
            print(f"  ✅ Written {len(ecom_content)} bytes → {ecom_path}")

            # JSON 也保留
            sel_data = build_selection_json(articles, img_map)
            json_path = os.path.join(day_dir, f"{today}_ecom_products.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(sel_data, f, ensure_ascii=False, indent=2)
            print(f"  📦 JSON: {len(sel_data)} items → {json_path}")
        else:
            print(f"  ✅ Written {len(content)} bytes → {md_path}")


if __name__ == "__main__":
    main()
