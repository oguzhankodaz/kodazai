"""PostgreSQL bağlantısı. Ortam değişkeni: DATABASE_URL"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
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


def init_db() -> None:
    import db.models  # noqa: F401 — QuestionLog vb. modeller metadata'ya kayılsın
    from db.models import Base

    Base.metadata.create_all(bind=engine)
