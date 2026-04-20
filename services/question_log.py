"""Konuşma başlangıcı, sorular ve verilen cevaplar question_log tablosuna yazılır (hata sohbeti kesmez)."""

from __future__ import annotations

from database import SessionLocal
from db.models import QuestionLog

KIND_USER_OPENING = "user_opening"
KIND_BOT_QUESTION = "bot_question"
KIND_USER_ANSWER = "user_answer"


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
