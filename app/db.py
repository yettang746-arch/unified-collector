"""Database setup and models."""
import os
import time
from sqlalchemy import create_engine, event, Column, Integer, Text, String, DateTime, Index
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError

DB_URL = os.environ.get("DB_URL", "")

if DB_URL:
    # PostgreSQL mode (production)
    engine = create_engine(DB_URL, echo=False, pool_size=20, max_overflow=10)
else:
    # SQLite mode (dev / legacy)
    DB_PATH = os.environ.get("DB_PATH", "/app/data/collector.db")
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """Enable WAL mode + busy timeout on every new connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(100), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)  # rss | rsshub | github_trending | telegram
    scope = Column(String(30), nullable=False, index=True)  # tech | cross-border | russia | selection
    category = Column(String(50), nullable=False, index=True)  # 二级分类
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False, unique=True)
    summary = Column(Text)
    full_text = Column(Text)  # 原文全文（仅RSS文章，TG帖子summary即全文）
    tags = Column(Text)  # JSON array string
    lang = Column(String(5), default="en")
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, nullable=False, index=True)
    raw_content = Column(Text)

    __table_args__ = (
        Index("idx_articles_scope", "scope"),
        Index("idx_articles_scope_cat", "scope", "category"),
        Index("idx_articles_fetched", "fetched_at"),
        Index("idx_articles_source", "source"),
    )


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def commit_with_retry(session, max_retries=3):
    """Commit with exponential backoff for transient DB errors."""
    for attempt in range(max_retries):
        try:
            session.commit()
            return
        except OperationalError:
            if attempt < max_retries - 1:
                sleep_sec = 2 ** attempt
                time.sleep(sleep_sec)
                session.rollback()
            else:
                raise
