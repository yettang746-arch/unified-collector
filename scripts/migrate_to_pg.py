"""Migrate data from SQLite (legacy) to PostgreSQL (new primary).

Usage: Run inside Docker after postgres is healthy:
    docker compose run --rm collector python scripts/migrate_to_pg.py
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Ensure /app is on the path when run from scripts/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

SQLITE_PATH = "/app/data/collector.db"
PG_URL = os.environ["DB_URL"]

CST = timezone(timedelta(hours=8))

# Connect to both
sqlite_engine = create_engine(f"sqlite:///{SQLITE_PATH}", connect_args={"check_same_thread": False})
pg_engine = create_engine(PG_URL, pool_size=5, max_overflow=5)

# Create tables in PG
from app.db import Base
Base.metadata.create_all(pg_engine)

PgSession = sessionmaker(bind=pg_engine)

def parse_dt(val):
    """Parse ISO datetime string or return None."""
    if not val:
        return None
    try:
        if isinstance(val, str):
            # Handle various formats
            for fmt in [
                "%Y-%m-%d %H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
            ]:
                try:
                    return datetime.strptime(val, fmt)
                except ValueError:
                    continue
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        return val
    except Exception:
        return None


def main():
    # Count source rows
    with sqlite_engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM articles")).scalar()
        print(f"📊 SQLite articles: {total}")

        if total == 0:
            print("⚠️  源数据库为空，跳过迁移")
            return

        # Fetch in batches
        batch_size = 500
        offset = 0
        migrated = 0
        skipped = 0

        while True:
            rows = conn.execute(
                text("SELECT * FROM articles ORDER BY id LIMIT :limit OFFSET :offset"),
                {"limit": batch_size, "offset": offset},
            ).fetchall()

            if not rows:
                break

            session = PgSession()
            try:
                for row in rows:
                    # Check if URL already exists in PG
                    existing = session.execute(
                        text("SELECT id FROM articles WHERE url = :url"),
                        {"url": row.url},
                    ).first()
                    if existing:
                        skipped += 1
                        continue

                    # Insert raw SQL to preserve all columns
                    session.execute(
                        text("""
                            INSERT INTO articles
                            (id, source, source_type, scope, category, title, url,
                             summary, full_text, tags, lang, published_at, fetched_at, raw_content)
                            VALUES
                            (:id, :source, :source_type, :scope, :category, :title, :url,
                             :summary, :full_text, :tags, :lang, :published_at, :fetched_at, :raw_content)
                        """),
                        {
                            "id": row.id,
                            "source": row.source,
                            "source_type": row.source_type or "rss",
                            "scope": row.scope or "uncategorized",
                            "category": row.category or "uncategorized",
                            "title": row.title or "",
                            "url": row.url or "",
                            "summary": row.summary or "",
                            "full_text": row.full_text or "",
                            "tags": row.tags or "",
                            "lang": row.lang or "en",
                            "published_at": parse_dt(row.published_at),
                            "fetched_at": parse_dt(row.fetched_at) or datetime.now(CST),
                            "raw_content": row.raw_content or "",
                        },
                    )
                    migrated += 1

                session.commit()
                print(f"  ✅ Batch {offset//batch_size + 1}: {migrated} migrated, {skipped} skipped")
            except Exception as e:
                session.rollback()
                print(f"  ❌ Batch error: {e}")
                raise
            finally:
                session.close()

            offset += batch_size

        print(f"\n✅ 迁移完成: {migrated} 条导入, {skipped} 条跳过 (共 {total} 条)")

    # Verify
    with pg_engine.connect() as conn:
        pg_total = conn.execute(text("SELECT COUNT(*) FROM articles")).scalar()
        print(f"📊 PostgreSQL articles: {pg_total}")

    if pg_total != total and skipped > 0:
        print(f"⚠️  PG 记录数 ({pg_total}) ≠ SQLite 记录数 ({total})，差异 = 已跳过 ({skipped})，正常")
    elif pg_total != total:
        print(f"❌ 数据不一致! PG: {pg_total}, SQLite: {total}")
        sys.exit(1)


if __name__ == "__main__":
    main()
