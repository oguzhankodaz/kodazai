"""
Mevcut veritabanında registry_entries tablosuna category sütununu ekler (bir kez).

Yeni kurulumlarda db.models üzerinden create_all zaten sütunu oluşturur;
eski bir Postgres şeması için bu betiği bir kez çalıştırın:

  python scripts/add_registry_category_column.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from database import engine, init_db  # noqa: E402


def main() -> None:
    init_db()
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE registry_entries ADD COLUMN IF NOT EXISTS category VARCHAR(128)"
            )
        )
    print("Tamam: registry_entries.category sütunu hazır.")


if __name__ == "__main__":
    main()
