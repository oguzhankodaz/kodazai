import re
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import init_db
from models.conversation_store import clear_conversation, get_conversation, save_conversation
from services.intent import classify_intent, parse_workflow_pick
from services.topic_search import search_matching_topics
from services.normalizer import normalize_answer
from services.workflow_engine import get_next_question, load_workflow, resolve
from services.workflow_store import (
    delete_workflow_file,
    list_workflow_files,
    load_registry,
    load_workflow_file,
    registry_workflows_newest_first,
    save_registry,
    save_workflow_file,
)
from services.question_log import log_bot_question, log_user_answer, log_user_opening
from services.workflow_validate import validate_registry, validate_workflow

app = FastAPI(title="Danışman AI")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class Message(BaseModel):
    conversation_id: str
    message: str


class NewWorkflowBody(BaseModel):
    code: str = Field(..., description="Dosya adı: ornek_akış")
    name: str = "Yeni süreç"
    clone_from: str | None = None


def _empty_workflow(code: str, name: str) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "questions": [],
        "rules": [],
        "default_result": {
            "title": "Tanımsız kombinasyon",
            "steps": ["Bu cevap kombinasyonu için kural ekleyin."],
            "warning": "",
        },
    }


def _ensure_registry_entry(code: str, label: str) -> None:
    """Akış dosyası varken registry'de yoksa iskelet satır ekler (Intent sekmesinde görünsün)."""
    reg = load_registry()
    reg_codes = {w.get("code") for w in reg.get("workflows", []) if w.get("code")}
    if code in reg_codes:
        return
    lab = (label or "").strip() or code
    reg.setdefault("workflows", []).insert(
        0,
        {
            "code": code,
            "label": lab,
            "description": "",
            "keywords": [code],
        },
    )
    ok, err = validate_registry(reg)
    if not ok:
        raise HTTPException(
            status_code=500,
            detail=f"Intent kaydı eklenemedi: {err}",
        ) from None
    save_registry(reg)


@app.get("/")
def index():
    return FileResponse("static/index.html", media_type="text/html; charset=utf-8")


@app.get("/admin")
def admin_page():
    return FileResponse("static/admin.html", media_type="text/html; charset=utf-8")


@app.get("/api/workflows")
def api_list_workflows():
    files = list_workflow_files()
    out = []
    for code in files:
        try:
            w = load_workflow_file(code)
            out.append({"code": code, "name": w.get("name", code)})
        except OSError:
            out.append({"code": code, "name": code, "error": True})
    reg = load_registry()
    reg_codes = {x["code"] for x in reg.get("workflows", [])}
    for item in out:
        item["in_registry"] = item["code"] in reg_codes
    return {"workflows": out}


@app.get("/api/registry")
def api_get_registry():
    return registry_workflows_newest_first(load_registry())


@app.put("/api/registry")
def api_put_registry(data: dict = Body(...)):
    ok, err = validate_registry(data)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    try:
        save_registry(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/workflow/{code}")
def api_get_workflow(code: str):
    try:
        return load_workflow_file(code)
    except OSError:
        raise HTTPException(status_code=404, detail="Akış bulunamadı.")


@app.put("/api/workflow/{code}")
def api_put_workflow(code: str, data: dict = Body(...)):
    if data.get("code") and data["code"] != code:
        raise HTTPException(status_code=400, detail="Gövde içindeki 'code' URL ile aynı olmalı.")
    data["code"] = code
    ok, err = validate_workflow(data)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    try:
        save_workflow_file(code, data)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    _ensure_registry_entry(code, str(data.get("name") or code))
    return {"ok": True}


@app.post("/api/workflow")
def api_create_workflow(body: NewWorkflowBody):
    code = body.code.strip().lower().replace("-", "_")
    if not _CODE_RE.match(code):
        raise HTTPException(
            status_code=400,
            detail="Kod: küçük harf, rakam ve alt çizgi; harf ile başlamalı.",
        )
    existing = list_workflow_files()
    if code in existing:
        raise HTTPException(status_code=409, detail="Bu kodda dosya zaten var.")

    if body.clone_from:
        try:
            data = load_workflow_file(body.clone_from.strip())
        except OSError:
            raise HTTPException(status_code=400, detail="Kopyalanacak akış bulunamadı.") from None
        data["code"] = code
        data["name"] = body.name
    else:
        data = _empty_workflow(code, body.name)

    ok, err = validate_workflow(data)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    save_workflow_file(code, data)
    _ensure_registry_entry(code, body.name.strip() or code)

    return {"ok": True, "code": code}


@app.delete("/api/workflow/{code}")
def api_delete_workflow(code: str):
    if code not in list_workflow_files():
        raise HTTPException(status_code=404, detail="Yok.")
    delete_workflow_file(code)
    reg = load_registry()
    reg["workflows"] = [w for w in reg.get("workflows", []) if w.get("code") != code]
    save_registry(reg)
    return {"ok": True}


@app.post("/message")
def message(data: Message):
    conv = get_conversation(data.conversation_id)

    # Önceki görüşmede tüm sorular cevaplanmışsa oturumu kapat;
    # aksi halde yeni mesaj yanlışlıkla tekrar sonuç üretir (soru sormadan).
    if conv:
        _wf = load_workflow(conv["workflow"])
        if get_next_question(_wf, conv["answers"]) is None:
            clear_conversation(data.conversation_id)
            conv = None

    yeni_konusma = False

    if not conv:
        msg = data.message.strip()
        picked = parse_workflow_pick(msg)

        if picked:
            intent = picked
        else:
            arama = search_matching_topics(msg)
            if len(arama) >= 1:
                return {
                    "type": "choose_intent",
                    "prompt": "Yazdığınız metne uyan konular. Devam etmek için birini seçin:",
                    "options": arama,
                }
            r = classify_intent(msg)
            if r["kind"] == "unknown":
                return {"message": "Ne yapmak istediğinizi anlayamadım"}
            if r["kind"] == "choose":
                return {
                    "type": "choose_intent",
                    "prompt": "Şunlardan birini seçerek devam edebilirsiniz:",
                    "options": r["candidates"],
                }
            intent = r["intent"]

        try:
            load_workflow(intent)
        except OSError:
            return {"message": "Geçersiz veya eksik akış dosyası."}

        conv = {
            "workflow": intent,
            "answers": {},
        }

        save_conversation(data.conversation_id, conv)
        yeni_konusma = True
        log_user_opening(data.conversation_id, intent, msg)

    workflow = load_workflow(conv["workflow"])

    if not yeni_konusma:
        last_q = get_next_question(workflow, conv["answers"])
        if last_q:
            normalized = normalize_answer(
                last_q["field"],
                data.message,
            )
            conv["answers"][last_q["field"]] = normalized
            log_user_answer(
                data.conversation_id,
                conv["workflow"],
                last_q["field"],
                normalized,
            )

    next_q = get_next_question(workflow, conv["answers"])

    if next_q:
        log_bot_question(
            data.conversation_id,
            conv["workflow"],
            str(next_q.get("field") or ""),
            str(next_q.get("question") or ""),
        )
        return {
            "type": "question",
            "question": next_q["question"],
            "options": next_q["options"],
        }

    result = resolve(workflow, conv["answers"])

    return {
        "type": "result",
        "result": result,
    }
