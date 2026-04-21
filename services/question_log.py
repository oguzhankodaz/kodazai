"""Konuşma başlangıcı, soru/cevaplar ve sonuç geri bildirimi question_log tablosuna yazılır."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from database import SessionLocal
from db.models import QuestionLog

KIND_USER_OPENING = "user_opening"
KIND_BOT_QUESTION = "bot_question"
KIND_USER_ANSWER = "user_answer"
KIND_RESULT_FEEDBACK = "result_feedback"


def log_user_opening(conversation_id: str, workflow_code: str, text: str) -> None:
    if not text or not text.strip():
        return
    try:
        with SessionLocal() as session:
            session.add(
                QuestionLog(
                    conversation_id=conversation_id[:128],
                    workflow_code=(workflow_code or "")[:128] or None,
                    kind=KIND_USER_OPENING,
                    field_name=None,
                    content=text.strip()[:20000],
                )
            )
            session.commit()
    except Exception:
        pass


def log_user_answer(
    conversation_id: str,
    workflow_code: str,
    field: str,
    answer_normalized: str,
) -> None:
    """Kullanıcının bir soruya verdiği cevap (kurallara yazılan normalize değer)."""
    if answer_normalized is None or str(answer_normalized).strip() == "":
        return
    try:
        with SessionLocal() as session:
            session.add(
                QuestionLog(
                    conversation_id=conversation_id[:128],
                    workflow_code=(workflow_code or "")[:128] or None,
                    kind=KIND_USER_ANSWER,
                    field_name=(field or "")[:256] or None,
                    content=str(answer_normalized).strip()[:20000],
                )
            )
            session.commit()
    except Exception:
        pass


def log_bot_question(
    conversation_id: str,
    workflow_code: str,
    field: str,
    question_text: str,
) -> None:
    if not question_text or not str(question_text).strip():
        return
    try:
        with SessionLocal() as session:
            session.add(
                QuestionLog(
                    conversation_id=conversation_id[:128],
                    workflow_code=(workflow_code or "")[:128] or None,
                    kind=KIND_BOT_QUESTION,
                    field_name=(field or "")[:256] or None,
                    content=str(question_text).strip()[:20000],
                )
            )
            session.commit()
    except Exception:
        pass


def log_result_feedback(
    conversation_id: str,
    workflow_code: str | None,
    solved: bool,
) -> None:
    """Sonuçtan sonra kullanıcının "çözüldü/çözülmedi" geri bildirimi."""
    try:
        with SessionLocal() as session:
            session.add(
                QuestionLog(
                    conversation_id=conversation_id[:128],
                    workflow_code=(workflow_code or "")[:128] or None,
                    kind=KIND_RESULT_FEEDBACK,
                    field_name="solved",
                    content="solved" if solved else "not_solved",
                )
            )
            session.commit()
    except Exception:
        pass


def _safe_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def get_journey_report(
    *,
    limit: int = 100,
    workflow_code: str | None = None,
    only_unsolved: bool = False,
) -> list[dict]:
    """
    Konuşma bazında yolculuk raporu döndürür.

    - Son konuşmalar öne alınır.
    - Her konuşma için olaylar zaman sırasına konur.
    """
    safe_limit = min(max(int(limit or 100), 1), 500)
    # limit konuşmaya uygulandığı için satır limiti daha geniş tutulur.
    row_cap = max(safe_limit * 60, 1000)

    with SessionLocal() as session:
        stmt = (
            select(QuestionLog)
            .order_by(QuestionLog.created_at.desc(), QuestionLog.id.desc())
            .limit(row_cap)
        )
        if workflow_code and workflow_code.strip():
            wf_query = workflow_code.strip()[:128]
            stmt = stmt.where(QuestionLog.workflow_code.ilike(f"%{wf_query}%"))
        rows = session.execute(stmt).scalars().all()

    selected_ids: list[str] = []
    by_conversation: dict[str, list[QuestionLog]] = defaultdict(list)
    selected_set: set[str] = set()

    for row in rows:
        cid = row.conversation_id
        if not cid:
            continue
        if cid not in selected_set:
            if len(selected_ids) >= safe_limit:
                continue
            selected_ids.append(cid)
            selected_set.add(cid)
        by_conversation[cid].append(row)

    report: list[dict] = []

    for cid in selected_ids:
        events = by_conversation.get(cid, [])
        events.sort(key=lambda x: (x.created_at or datetime.min, x.id or 0))
        if not events:
            continue

        opening_text: str | None = None
        conv_workflow: str | None = None
        result_feedback: str | None = None
        journey: list[dict] = []

        for ev in events:
            if not conv_workflow and ev.workflow_code:
                conv_workflow = ev.workflow_code

            if ev.kind == KIND_USER_OPENING and not opening_text:
                opening_text = ev.content

            if ev.kind == KIND_RESULT_FEEDBACK:
                result_feedback = ev.content

            journey.append(
                {
                    "kind": ev.kind,
                    "field_name": ev.field_name,
                    "content": ev.content,
                    "created_at": _safe_iso(ev.created_at),
                }
            )

        status = "unknown"
        if result_feedback == "solved":
            status = "solved"
        elif result_feedback == "not_solved":
            status = "not_solved"

        if only_unsolved and status != "not_solved":
            continue

        report.append(
            {
                "conversation_id": cid,
                "workflow_code": conv_workflow,
                "opening_text": opening_text,
                "status": status,
                "event_count": len(journey),
                "started_at": _safe_iso(events[0].created_at),
                "ended_at": _safe_iso(events[-1].created_at),
                "journey": journey,
            }
        )

    return report
