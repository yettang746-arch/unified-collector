#!/usr/bin/python3
"""
独立图片补下载脚本。
用法：python3 download-selection-images.py [--date YYYY-MM-DD] [--scope selection]

从 selection.json 或 ecom_products.json 读取图片 URL，并发下载到 images/ 目录。
支持断点续传（已存在的文件自动跳过）。
"""
import json
import os
import sys
import time
import urllib.request
import ssl
import certifi
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

BASE_DIR = "/Users/zijun/.openclaw/workspace-team/daily-article/russian-market/inbox"

IMG_TIMEOUT = 5       # 单张超时
IMG_WORKERS = 10       # 并发数
TOTAL_DEADLINE = 120   # 总超时（秒）
MAX_IMGS_PER_ITEM = 3  # 每条最多几张


def download_images_for_date(date_str: str):
    """为指定日期下载选品图片。"""
    # 找 selection.json 或 ecom_products.json
    sel_path = os.path.join(BASE_DIR, date_str, f"{date_str}_selection.json")
    ecom_path = os.path.join(BASE_DIR, date_str, f"{date_str}_ecom_products.json")

    json_path = None
    if os.path.exists(sel_path):
        json_path = sel_path
    elif os.path.exists(ecom_path):
        json_path = ecom_path

    if not json_path:
        print(f"❌ 未找到 {date_str} 的选品数据文件")
        return False

    print(f"📂 读取: {json_path}")
    with open(json_path) as f:
        items = json.load(f)
    print(f"  共 {len(items)} 条数据")

    img_dir = os.path.join(BASE_DIR, date_str, "images")
    os.makedirs(img_dir, exist_ok=True)

    tasks = []
    existing_count = 0
    for idx, item in enumerate(items):
        raw_content = item.get("raw_content", "")
        if not raw_content:
            continue
        try:
            rc = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            images = rc.get("images", [])
        except Exception:
            continue
        if not images:
            continue

        src = item.get("source", "unknown").replace("/", "_").replace(" ", "_")[:30]
        for img_idx, url in enumerate(images[:MAX_IMGS_PER_ITEM]):
            ext = ".jpg"
            if ".png" in url:
                ext = ".png"
            elif ".webp" in url:
                ext = ".webp"
            fname = f"{src}_{idx}_{img_idx}{ext}"
            fpath = os.path.join(img_dir, fname)
            if os.path.exists(fpath):
                existing_count += 1
            else:
                tasks.append((fname, url, fpath))

    if not tasks:
        print(f"✅ 所有图片已存在 ({existing_count} 张)")
        return True

    print(f"  已有: {existing_count} 张 | 待下载: {len(tasks)} 张")
    print(f"  并发: {IMG_WORKERS} | 总超时: {TOTAL_DEADLINE}s")

    done = fail = 0
    start = time.monotonic()

    def _dl(args):
        fname, url, fpath = args
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=IMG_TIMEOUT, context=SSL_CTX) as r:
                if r.status == 200:
                    with open(fpath, "wb") as f:
                        f.write(r.read())
                    return True
        except Exception:
            pass
        # Fallback: curl
        import subprocess
        try:
            result = subprocess.run(
                ["curl", "-sS", "-m", "5", "-o", fpath, url],
                capture_output=True, timeout=8
            )
            if result.returncode == 0 and os.path.exists(fpath) and os.path.getsize(fpath) > 100:
                return True
        except Exception:
            pass
        return False

    with ThreadPoolExecutor(max_workers=IMG_WORKERS) as pool:
        futures = [pool.submit(_dl, t) for t in tasks]
        for fut in futures:
            remaining = TOTAL_DEADLINE - (time.monotonic() - start)
            if remaining <= 0:
                print(f"⚠️ 总超时，已处理 {done+fail}/{len(tasks)}")
                pool.shutdown(wait=False, cancel_futures=True)
                break
            try:
                ok = fut.result(timeout=max(remaining, 1))
            except Exception:
                ok = False
            if ok:
                done += 1
            else:
                fail += 1

    total = len(os.listdir(img_dir))
    elapsed = time.monotonic() - start
    print(f"\n📊 结果: {done} 成功, {fail} 失败 | 目录总计: {total} 张 | 耗时: {elapsed:.1f}s")
    print(f"📁 目录: {img_dir}")
    return fail == 0


def main():
    parser = argparse.ArgumentParser(description="独立图片补下载")
    parser.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--days", type=int, default=1, help="回溯几天（默认1）")
    args = parser.parse_args()

    if args.date:
        dates = [args.date]
    else:
        today = datetime.now(CST)
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    for d in dates:
        print(f"\n{'='*50}")
        print(f"📅 {d}")
        download_images_for_date(d)


if __name__ == "__main__":
    main()
