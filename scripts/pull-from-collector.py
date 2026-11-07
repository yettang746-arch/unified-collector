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

API_PAGE_LIMIT = 500      # 单页拉取上限
MAX_PAGES = 20            # 分页安全上限，防止接口 total 异常导致死循环


def _fetch_articles_page(scope: str, date_str: str, offset: int, limit: int) -> tuple:
    """拉取单页文章，返回 (articles, total)。

    total 为 None 表示接口未返回总数字段，此时只能按本页数量判断是否继续。
    """
    url = (f"{API_URL}/api/v1/articles?scope={scope}&date={date_str}"
           f"&limit={limit}&offset={offset}")
    # Prefer curl (avoids Python SSL issues on some hosts)
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-sS", "-m", "30", "-H", f"Authorization: Bearer {API_KEY}", url],
            capture_output=True, text=True, timeout=35
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            return data.get("articles", []), data.get("total")
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
    return data.get("articles", []), data.get("total")


def fetch_articles(scope: str, date_str: str) -> list:
    """分页拉取当天全部文章。

    2026-11-07 修复：此前固定 limit=500 且不做分页，接口 total=587 时静默丢掉 87 条，
    下游选品数据不完整。改为按 total 循环翻页。
    """
    all_articles = []
    offset = 0
    total = None
    for _ in range(MAX_PAGES):
        try:
            articles, page_total = _fetch_articles_page(scope, date_str, offset, API_PAGE_LIMIT)
        except Exception as e:
            print(f"  WARN page fetch failed offset={offset}: {e}")
            break
        if page_total is not None:
            total = page_total
        if not articles:
            break
        all_articles.extend(articles)
        offset += len(articles)
        if total is None:
            # 接口没给 total：只有拉满一页才继续翻下一页
            if len(articles) < API_PAGE_LIMIT:
                break
            continue
        if offset >= total:
            break
    if total is not None and len(all_articles) < total:
        print(f"  WARN incomplete pagination: {len(all_articles)}/{total}")
    return all_articles


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
            # 过滤无效full_text（Cloudflare挑战页、付费墙、JS乱码）
            full_text = (a.get("full_text") or "").strip()
            summary = (a.get("summary") or "").strip()[:150]
            if full_text:
                ft_lower = full_text.lower()
                # 检测Cloudflare/JS挑战页、CSS规则、付费墙等无效内容
                if any(p in ft_lower for p in [
                    "enable javascript", "window._cf_chl_opt", ".logo{margin",
                    "function(){"[:12], "cf_chl_rt_tk", "member exclusive",
                    "cookies to continue", "lock,.logo{display"
                ]):
                    full_text = ""  # 淘汰，走summary

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
        # img_map 的 key 是 (article_idx, product_idx)，按商品维度收集本地图片
        local_imgs = []
        if img_map:
            for pi in range(len(_extract_product_images(a.get("raw_content", ""))) or 1):
                local_imgs.extend(img_map.get((idx, pi), []))
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


_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM")
_IMG_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# 每个商品最多下载几张图（补下载脚本 download-selection-images.py 需与之保持一致）
MAX_IMGS_PER_PRODUCT = 2


def _is_valid_image_file(path: str) -> bool:
    """内容级校验：magic bytes + 最小体积。

    CDN 超时/500 时会返回 198 字节的 nginx HTML 错误页，
    仅用 os.path.exists() 判定会把垃圾图当成"已缓存"，造成假绿。
    """
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 1024:
            return False
        with open(path, "rb") as f:
            head = f.read(16)
        low = head.lower()
        if b"<html" in low or b"<!doc" in low:
            return False
        return any(head.startswith(m) for m in _IMAGE_MAGIC)
    except OSError:
        return False


def _download_image(url: str, save_path: str) -> bool:
    """下载图片到本地，返回是否成功（内容校验通过才算成功）。

    先写 .part 临时文件，校验通过再 replace，避免失败时在磁盘留下垃圾文件。
    """
    import subprocess
    tmp_path = save_path + ".part"
    try:
        result = subprocess.run(
            ["curl", "-sS", "-L", "--compressed", "-m", "15",
             "-H", f"User-Agent: {_IMG_UA}",
             "-H", "Referer: https://telesco.pe/",
             "-o", tmp_path, url],
            capture_output=True, timeout=25
        )
        if result.returncode == 0 and _is_valid_image_file(tmp_path):
            os.replace(tmp_path, save_path)
            return True
    except Exception:
        pass
    # Fallback to urllib
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _IMG_UA})
        ctx = _ssl_ctx()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            if resp.status == 200:
                with open(tmp_path, "wb") as f:
                    f.write(resp.read())
                if _is_valid_image_file(tmp_path):
                    os.replace(tmp_path, save_path)
                    return True
    except Exception as e:
        print(f"    ⚠️ 下载失败 {url[:60]}...: {e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return False


def _extract_product_images(raw_content: str) -> list:
    """从 raw_content 提取商品级图片列表。
    新格式: {products: [{text, images, links}], images: [...], links: [...]}
    旧格式: {images: [...], links: [...]}
    返回: [{"text": ..., "images": [...], "links": [...]}]
    """
    if not raw_content:
        return []
    try:
        rc = json.loads(raw_content)
    except Exception:
        return []
    products = rc.get("products", [])
    if products:
        return products
    # 旧格式兼容
    images = rc.get("images", [])
    links = rc.get("links", [])
    if images or links:
        return [{"text": "", "images": images, "links": links}]
    return []


def _download_article_images(articles: list, img_dir: str) -> dict:
    """批量下载文章图片到指定目录（并发+总超时）。
    返回 {(article_idx, product_idx): [local_paths]}，按商品维度绑定图片。
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    IMG_WORKERS = 10
    TOTAL_DEADLINE = 300

    os.makedirs(img_dir, exist_ok=True)
    result = {}
    total = 0
    tasks = []

    for idx, a in enumerate(articles):
        products = _extract_product_images(a.get("raw_content", ""))
        if not products:
            continue
        src = a.get("source", "unknown").replace("/", "_").replace(" ", "_")[:30]
        for p_idx, product in enumerate(products):
            images = product.get("images", [])
            if not images:
                continue
            for i, img_url in enumerate(images[:MAX_IMGS_PER_PRODUCT]):
                ext = ".jpg"
                if ".png" in img_url:
                    ext = ".png"
                elif ".webp" in img_url:
                    ext = ".webp"
                filename = f"{src}_{idx}_p{p_idx}_{i}{ext}"
                save_path = os.path.join(img_dir, filename)
                key = (idx, p_idx)
                if _is_valid_image_file(save_path):
                    result.setdefault(key, []).append(save_path)
                else:
                    # 存在但内容无效（HTML 错误页/截断）→ 重新下载
                    if os.path.exists(save_path):
                        try:
                            os.remove(save_path)
                        except OSError:
                            pass
                    total += 1
                    tasks.append((key, img_url, save_path))

    if not tasks:
        existing = sum(len(v) for v in result.values())
        print(f"  📷 图片已全部存在 ({existing} 张)")
        return result

    print(f"  📷 下载 {len(tasks)} 张图片（并发 {IMG_WORKERS}，总超时 {TOTAL_DEADLINE}s）...")
    start = _time.monotonic()
    ok = 0
    fail = 0

    with ThreadPoolExecutor(max_workers=IMG_WORKERS) as pool:
        futures = {pool.submit(_download_image, url, path): (key, path) for key, url, path in tasks}
        for fut in list(futures):
            remaining = TOTAL_DEADLINE - (_time.monotonic() - start)
            if remaining <= 0:
                print(f"  ⚠️ 图片下载总超时，已处理 {ok+fail}/{len(tasks)}")
                pool.shutdown(wait=False, cancel_futures=True)
                break
            key, path = futures[fut]
            try:
                success = fut.result(timeout=max(remaining, 1))
            except Exception:
                success = False
            if success:
                ok += 1
                result.setdefault(key, []).append(path)
            else:
                fail += 1

    existing = sum(len(v) for v in result.values())
    print(f"  📷 图片: {ok} 新下载, {fail} 失败 | 总计: {existing} 张 → {img_dir}")
    return result


def build_ecom_products_md(articles: list, date_str: str, img_map: dict = None) -> str:
    """按 source 分组输出选品数据，每个商品单独配图+描述+链接。
    img_map 格式: {(article_idx, product_idx): [local_paths]}
    """
    import re

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
            global_idx = None
            for gi, ga in enumerate(articles):
                if ga is a:
                    global_idx = gi
                    break

            title = a.get("title", "").strip()
            pub = a.get("published_at", "")
            pub_short = ""
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub)
                    pub_short = dt.strftime("%a,")
                except Exception:
                    pass

            # 提取商品级数据
            products = _extract_product_images(a.get("raw_content", ""))

            if not products:
                # 无 raw_content，用 summary 兜底
                desc = a.get("summary", "").strip()
                links = re.findall(r'https?://[^\s)"<>]+', desc)
                url = a.get("url", "")
                if url and url not in links:
                    links.insert(0, url)
                local_imgs = img_map.get((global_idx, 0), []) if img_map else []

                lines.append(f"### [{pub_short}] {title}")
                lines.append("")
                if local_imgs:
                    for lp in local_imgs:
                        lines.append(f"![img]({lp})")
                    lines.append("")
                if desc:
                    lines.append(desc)
                    lines.append("")
                if links:
                    lines.append("**链接:**")
                    for lnk in links[:10]:
                        lines.append(f"- {lnk}")
                lines.append("")
                lines.append("---")
                lines.append("")
                continue

            # 有商品级配对：逐商品输出
            for p_idx, product in enumerate(products):
                p_text = product.get("text", "").strip()
                p_images = product.get("images", [])
                p_links = product.get("links", [])

                # 商品标题：如果多商品，标题加序号；单商品用原 title
                if len(products) > 1:
                    p_title = f"{title} ({p_idx + 1}/{len(products)})"
                else:
                    p_title = title

                lines.append(f"### [{pub_short}] {p_title}")
                lines.append("")

                # 图片：优先本地，fallback 远程
                local_imgs = img_map.get((global_idx, p_idx), []) if img_map else []
                if local_imgs:
                    for lp in local_imgs:
                        lines.append(f"![img]({lp})")
                    lines.append("")
                elif p_images:
                    for img in p_images[:2]:
                        lines.append(f"![img]({img})")
                    lines.append("")

                # 描述
                desc = p_text or a.get("summary", "").strip()
                if desc:
                    lines.append(desc)
                    lines.append("")

                # 链接
                if p_links:
                    lines.append("**链接:**")
                    for lnk in p_links[:10]:
                        lines.append(f"- {lnk}")
                else:
                    links = re.findall(r'https?://[^\s)"<>]+', p_text)
                    url = a.get("url", "")
                    if url and url not in links:
                        links.insert(0, url)
                    if links:
                        lines.append("**链接:**")
                        for lnk in links[:10]:
                            lines.append(f"- {lnk}")

                # 标签
                tags = re.findall(r'#\w+', p_text)
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
    parser.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD（默认今天 CST）")
    parser.add_argument("--merge-cross-border", action="store_true",
                        help="russia scope 时额外拉取 cross-border 并融合到 russia.md")
    args = parser.parse_args()

    scopes = ["tech", "cross-border", "russia", "selection"] if args.all else [args.scope]

    # 统一用北京时间日期
    today = args.date if args.date else datetime.now(CST).strftime("%Y-%m-%d")

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
        elif scope == "russia" and args.merge_cross_border:
            content = build_inbox_md(articles, scope, today)
            # 额外拉取 cross-border
            cb_articles = fetch_articles("cross-border", today)
            if cb_articles:
                cb_content = build_inbox_md(cb_articles, "cross-border", today)
                merged = content + "\n\n" + cb_content
            else:
                merged = content
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(merged + "\n")
            print(f"  ✅ Merged {len(articles)} russia + {len(cb_articles)} cross-border → {md_path}")
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

            # 原始选品数据（含 raw_content），供下游按原始 URL 重建补下载任务
            raw_sel_path = os.path.join(day_dir, f"{today}_selection.json")
            raw_items = []
            for i, art in enumerate(articles):
                item = dict(art)
                item["idx"] = i
                raw_items.append(item)
            with open(raw_sel_path, "w", encoding="utf-8") as f:
                json.dump(raw_items, f, ensure_ascii=False, indent=2)
            print(f"  🧾 原始数据: {len(raw_items)} items → {raw_sel_path}")
        else:
            print(f"  ✅ Written {len(content)} bytes → {md_path}")


if __name__ == "__main__":
    main()
