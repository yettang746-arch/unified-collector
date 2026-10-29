#!/usr/bin/python3
"""
选品图片修复脚本（内容校验 + 重下）。

用法：python3 repair-selection-images.py [--date YYYY-MM-DD] [--scope selection]

背景：pull-from-collector.py 的 _download_image() 只校验「文件存在且 size > 100 字节」，
所以 CDN 返回的 198 字节 nginx 500 错误页会被当成「下载成功」，脚本打印的
「N 新下载, 0 失败」是假绿。本脚本按内容重新校验已落盘的图片，把无效的
（HTML 错误页 / 0 字节 / 非图片 magic bytes）重下并覆盖。

已损坏的文件会按 remote URL 重试下载（带 UA + Referer），
只有通过图片 magic bytes 校验才写回。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
BASE_DIR = "/Users/zijun/.openclaw/workspace-team/daily-article/russian-market/inbox"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"\x00\x00\x00")
MIN_BYTES = 1024
MAX_ATTEMPTS = 4


def is_valid_image(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) < MIN_BYTES:
        return False
    with open(path, "rb") as f:
        head = f.read(16)
    if b"<html" in head.lower() or b"<!doc" in head.lower():
        return False
    return any(head.startswith(m) for m in MAGIC)


def fetch(url: str, dest: str) -> bool:
    """下载到 dest，只有内容是合法图片才返回 True。"""
    tmp = dest + ".retry"
    for attempt in range(MAX_ATTEMPTS):
        try:
            subprocess.run(
                ["curl", "-sS", "-L", "--compressed", "-m", "20",
                 "-H", f"User-Agent: {UA}",
                 "-H", "Referer: https://telesco.pe/",
                 "-o", tmp, url],
                capture_output=True, timeout=30,
            )
            if is_valid_image(tmp):
                os.replace(tmp, dest)
                return True
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception as e:  # noqa: BLE001
            print(f"    ⚠️ 第 {attempt + 1} 次尝试异常: {e}")
        time.sleep(2 + attempt * 2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(CST).strftime("%Y-%m-%d"))
    ap.add_argument("--scope", default="selection")
    args = ap.parse_args()

    day_dir = os.path.join(BASE_DIR, args.date)
    json_path = os.path.join(day_dir, f"{args.date}_ecom_products.json")
    sel_path = os.path.join(day_dir, f"{args.date}_selection.json")
    if os.path.exists(sel_path):
        json_path = sel_path
    if not os.path.exists(json_path):
        print(f"❌ 未找到选品数据文件: {json_path}")
        return 1

    with open(json_path, encoding="utf-8") as f:
        items = json.load(f)

    pairs = []  # (remote_url, local_path)
    for it in items:
        for u, p in zip(it.get("images") or [], it.get("local_images") or []):
            if u and p:
                pairs.append((u, p))

    broken = [(u, p) for u, p in pairs if not is_valid_image(p)]
    print(f"📅 {args.date} | 数据 {len(items)} 条 | 图片引用 {len(pairs)} 张 | "
          f"损坏 {len(broken)} 张")
    if not broken:
        print("  ✅ 全部图片内容校验通过")
        return 0

    fixed, failed = [], []
    for url, path in broken:
        if fetch(url, path):
            fixed.append(os.path.basename(path))
        else:
            failed.append(os.path.basename(path))

    print(f"  🔧 修复 {len(fixed)} 张，仍失败 {len(failed)} 张")
    for f in fixed:
        print(f"    ✅ {f}")
    for f in failed:
        print(f"    ❌ {f}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
