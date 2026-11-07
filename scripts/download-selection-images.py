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


def _load_max_imgs_per_product() -> int:
    """与主拉取脚本 pull-from-collector.py 保持一致，避免补下载产生未引用/错位文件。"""
    try:
        import importlib.util
        pull_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pull-from-collector.py")
        spec = importlib.util.spec_from_file_location("pull_from_collector", pull_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return int(getattr(mod, "MAX_IMGS_PER_PRODUCT", 2))
    except Exception:
        return 2


MAX_IMGS_PER_PRODUCT = _load_max_imgs_per_product()

_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM")


def is_valid_image_file(path: str) -> bool:
    """内容级校验：magic bytes + 最小体积（防 nginx 500 HTML 错误页）。"""
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

    # 与主拉取脚本 pull-from-collector.py 对齐：
    # 兼容两种数据源：
    #  A) selection.json -> 每条含 raw_content(products结构)
    #  B) ecom_products.json -> 每条 image 字段即远程URL列表（每日实际场景）
    # 文件名格式 {src}_{idx}_p{p_idx}_{i}.ext（关键：带 _p{p_idx} 段，
    #  否则无法识别主脚本已下载的文件，导致误报“所有图片已存在”。
    def extract_sources(item):
        """返回 [(远程url, p_idx, i_in_product), ...]

        i_in_product 必须是“该商品内第几张图”，与主拉取脚本的文件名规则
        `{src}_{idx}_p{p_idx}_{i}` 严格一致，否则会生成错位文件名。
        """
        raw = item.get("raw_content", "")
        if raw:
            try:
                rc = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                rc = None
            if rc:
                products = rc.get("products", [])
                if products:
                    out = []
                    for pi, p in enumerate(products):
                        for i, u in enumerate(p.get("images", [])[:MAX_IMGS_PER_PRODUCT]):
                            out.append((u, pi, i))
                    return out
                out = []
                for i, u in enumerate(rc.get("images", [])[:MAX_IMGS_PER_PRODUCT]):
                    out.append((u, 0, i))
                return out
        # ecom_products.json: 无 raw_content，无法还原主脚本的 p_idx 分组，
        # 若直接按平铺 images 重构文件名会与主脚本错位、产生多余文件。
        # 故此处只读校验 local_images 是否缺失，不做新下载（用重跑主脚本补全）。
        return []

    tasks = []
    existing_count = 0
    for pos, item in enumerate(items):
        src_pairs = extract_sources(item)
        if not src_pairs:
            continue
        idx = item.get("idx", pos)
        src = item.get("source", "unknown").replace("/", "_").replace(" ", "_")[:30]
        seen = set()
        for url, p_idx, i_idx in src_pairs[:MAX_IMGS_PER_PRODUCT * 10]:
            if (p_idx, i_idx) in seen:
                continue
            seen.add((p_idx, i_idx))
            ext = ".jpg"
            if ".png" in url:
                ext = ".png"
            elif ".webp" in url:
                ext = ".webp"
            fname = f"{src}_{idx}_p{p_idx}_{i_idx}{ext}"
            fpath = os.path.join(img_dir, fname)
            if is_valid_image_file(fpath):
                existing_count += 1
            else:
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
                tasks.append((fname, url, fpath))

    if not tasks:
        if json_path == ecom_path:
            # 只读校验：核对 local_images 引用是否缺失（ecom json 无 raw_content，
            # 无法重建下载任务，缺失时提示用重跑主脚本补全，避免错位文件）
            missing = []
            for item in items:
                for p in (item.get("local_images") or []):
                    if p and not is_valid_image_file(p):
                        missing.append(p)
            if missing:
                print(f"  ⚠️ {len(missing)} 张 local_images 引用的图片缺失（可能需重跑主拉取脚本补全）:")
                for p in missing[:10]:
                    print(f"    - {p}")
                return False
            else:
                print(f"  ✅ 所有图片已存在，且 local_images 引用完整 ({existing_count} 张)")
                return True
        print(f"✅ 所有图片已存在 ({existing_count} 张)")
        return True

    print(f"  已有: {existing_count} 张 | 待下载: {len(tasks)} 张")
    print(f"  并发: {IMG_WORKERS} | 总超时: {TOTAL_DEADLINE}s")

    done = fail = 0
    start = time.monotonic()

    def _dl(args):
        fname, url, fpath = args
        tmp_path = fpath + ".part"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=IMG_TIMEOUT, context=SSL_CTX) as r:
                if r.status == 200:
                    with open(tmp_path, "wb") as f:
                        f.write(r.read())
                    if is_valid_image_file(tmp_path):
                        os.replace(tmp_path, fpath)
                        return True
        except Exception:
            pass
        # Fallback: curl
        import subprocess
        try:
            result = subprocess.run(
                ["curl", "-sS", "-m", "5", "-o", tmp_path, url],
                capture_output=True, timeout=8
            )
            if result.returncode == 0 and is_valid_image_file(tmp_path):
                os.replace(tmp_path, fpath)
                return True
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
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
