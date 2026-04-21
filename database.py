"""PostgreSQL bağlantısı. Ortam değişkeni: DATABASE_URL"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL tanımlı değil. Örnek:\n"
        "  set DATABASE_URL=postgresql://kullanici:sifre@localhost:5432/danisman\n"
        "  (Linux/macOS: export DATABASE_URL=...)"
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _ensure_registry_category_column() -> None:
    """Eski şemalarda registry_entries.category yoksa ekler (create_all sütun eklemez)."""
    stmt = text(
        """
        DO $m$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'registry_entries'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'registry_entries'
                  AND column_name = 'category'
            ) THEN
                ALTER TABLE registry_entries ADD COLUMN category VARCHAR(128);
            END IF;
        END
        $m$;
        """
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def init_db() -> None:
    import db.models  # noqa: F401 — QuestionLog vb. modeller metadata'ya kayılsın
    from db.models import Base

    Base.metadata.create_all(bind=engine)
    _ensure_registry_category_column()
