"""
İsteğe bağlı: proje kökündeki workflows/ klasörüne koyduğunuz yedek
*.json ve registry.json dosyalarını PostgreSQL'e aktarır (normal kullanımda gerekmez).

Önce DATABASE_URL ve çalışan Postgres gerekir; tablolar yoksa oluşturulur.

Kullanım (proje kökünden):
  python scripts/import_json_files.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database import init_db  # noqa: E402
from services.workflow_store import save_registry, save_workflow_file  # noqa: E402


def main() -> None:
    init_db()
    wf_dir = ROOT / "workflows"
    if not wf_dir.is_dir():
        print("Klasör yok:", wf_dir)
        sys.exit(1)

    for p in sorted(wf_dir.glob("*.json")):
        if p.name == "registry.json":
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        code = str(data.get("code") or p.stem).strip()
        save_workflow_file(code, data)
        print("Akış yüklendi:", code)

    reg_path = wf_dir / "registry.json"
    if reg_path.is_file():
        with open(reg_path, encoding="utf-8") as f:
            reg = json.load(f)
        save_registry(reg)
        print("Intent registry yüklendi.")
    else:
        print("registry.json bulunamadı; atlandı.")

    print("Bitti.")


if __name__ == "__main__":
    main()
