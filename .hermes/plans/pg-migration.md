# unified-collector SQLite → PostgreSQL 迁移方案

> **For Hermes:** 按顺序执行，每步验证后再下一步。

**目标：** 将 unified-collector 从 SQLite 迁移到 PostgreSQL，解决并发写入 `database is locked` 问题。

**架构：** docker-compose 新增 `postgres` 服务，app 通过 `DB_URL` 环境变量连接。

---

## Task 1: docker-compose.yml — 新增 PostgreSQL 服务

在 `/root/unified-collector/docker-compose.yml` 添加：

```yaml
  postgres:
    image: postgres:16-alpine
    container_name: collector-pg
    restart: unless-stopped
    environment:
      POSTGRES_DB: collector
      POSTGRES_USER: collector
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U collector"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  pg_data:
```

在 app 的 `environment` 中加：
```yaml
      - DB_URL=postgresql://collector:${PG_PASSWORD}@postgres:5432/collector
```

---

## Task 2: app/db.py — 支持 PostgreSQL

把 `create_engine` 改为：

```python
import os
from sqlalchemy import create_engine

DB_URL = os.environ.get("DB_URL", "")

if DB_URL:
    engine = create_engine(DB_URL, echo=False, pool_size=20, max_overflow=10)
else:
    DB_PATH = os.environ.get("DB_PATH", "/app/data/collector.db")
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
```

`url` 字段从 `Text` 改为 `Text` 即可（PG 支持 TEXT 类型）。

---

## Task 3: requirements.txt — 加 psycopg2

```
psycopg2-binary==2.9.9
```

---

## Task 4: collector.py — 加重试逻辑

在 `session.commit()` 外包重试：

```python
import time
from sqlalchemy.exc import OperationalError

def _commit_with_retry(session, max_retries=3):
    for attempt in range(max_retries):
        try:
            session.commit()
            return
        except OperationalError:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                session.rollback()
            else:
                raise
```

---

## Task 5: 数据迁移脚本

创建 `scripts/migrate_to_pg.py` — 从 SQLite 读取所有数据写入 PG。PG 连接信息从环境变量取。

---

## Task 6: .env 更新

```
API_KEY=cbtc_2026_k3y
PG_PASSWORD=collector_pg_2026
```

---

## Task 7: 部署

```bash
cd /root/unified-collector
docker compose down collector
docker compose up -d postgres
# 等 PG healthy 后
docker compose run --rm collector python scripts/migrate_to_pg.py
docker compose up -d --build collector
```
