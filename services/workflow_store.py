"""Akış ve intent verisi — PostgreSQL (DATABASE_URL)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from db.models import RegistryEntry, Workflow


def _session() -> Session:
    return SessionLocal()


def list_workflow_files() -> list[str]:
    with _session() as session:
        rows = session.scalars(select(Workflow.code).order_by(Workflow.code)).all()
        return list(rows)


def workflow_json_mtime(code: str) -> float:
    with _session() as session:
        row = session.get(Workflow, code)
        if row is None or row.updated_at is None:
            return -1.0
        return row.updated_at.timestamp()


def registry_workflows_newest_first(reg: dict[str, Any]) -> dict[str, Any]:
    wfs = list(reg.get("workflows", []))
    if not wfs:
        return reg
    codes = [str(x.get("code") or "") for x in wfs if x.get("code")]
    with _session() as session:
        stmt = select(Workflow.code, Workflow.updated_at).where(Workflow.code.in_(codes))
        rows = session.execute(stmt).all()
    mt = {
        r.code: (r.updated_at.timestamp() if r.updated_at else 0.0) for r in rows
    }

    def sort_key(entry: dict[str, Any]) -> tuple[float, str]:
        c = str(entry.get("code") or "")
        return (mt.get(c, -1.0), c)

    wfs.sort(key=sort_key, reverse=True)
    return {**reg, "workflows": wfs}


def _entry_to_dict(row: RegistryEntry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "code": row.code,
        "label": row.label,
        "description": row.description or "",
        "keywords": list(row.keywords) if row.keywords is not None else [],
    }
    if row.strict:
        d["strict"] = row.strict
    return d


def load_registry() -> dict:
    with _session() as session:
        stmt = (
            select(RegistryEntry)
            .join(Workflow, RegistryEntry.code == Workflow.code)
            .order_by(Workflow.updated_at.desc())
        )
        rows = session.scalars(stmt).all()
        return {
            "version": 1,
            "workflows": [_entry_to_dict(r) for r in rows],
        }


def save_registry(data: dict) -> None:
    wfs = data.get("workflows")
    if not isinstance(wfs, list):
        wfs = []
    new_codes = {str(w["code"]).strip() for w in wfs if isinstance(w, dict) and w.get("code")}

    with _session() as session:
        for row in session.scalars(select(RegistryEntry)).all():
            if row.code not in new_codes:
                session.delete(row)

        for w in wfs:
            if not isinstance(w, dict):
                continue
            code = str(w.get("code", "")).strip()
            if not code:
                continue
            if session.get(Workflow, code) is None:
                session.rollback()
                raise ValueError(f"Intent kaydı için akış yok: {code}")

            kw = w.get("keywords") or []
            if not isinstance(kw, list):
                kw = []
            st = w.get("strict")
            if st is not None and not isinstance(st, dict):
                st = None
            label = str(w.get("label") or code)
            desc = str(w.get("description") or "")

            ent = session.get(RegistryEntry, code)
            if ent:
                ent.label = label
                ent.description = desc
                ent.keywords = kw
                ent.strict = st
            else:
                session.add(
                    RegistryEntry(
                        code=code,
                        label=label,
                        description=desc,
                        keywords=kw,
                        strict=st,
                    )
                )
        session.commit()


def load_workflow_file(code: str) -> dict:
    with _session() as session:
        row = session.get(Workflow, code)
        if row is None:
            raise FileNotFoundError(code)
        doc = row.document
        if not isinstance(doc, dict):
            raise FileNotFoundError(code)
        return doc


def save_workflow_file(code: str, data: dict) -> None:
    now = datetime.now(timezone.utc)
    with _session() as session:
        row = session.get(Workflow, code)
        if row is None:
            session.add(
                Workflow(code=code, document=data, updated_at=now),
            )
        else:
            row.document = data
            row.updated_at = now
        session.commit()


def delete_workflow_file(code: str) -> None:
    with _session() as session:
        row = session.get(Workflow, code)
        if row is not None:
            session.delete(row)
            session.commit()
