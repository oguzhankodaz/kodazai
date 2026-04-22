import os
import re
from urllib.parse import quote
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from database import init_db
from models.conversation_store import clear_conversation, get_conversation, save_conversation
from services.auth import ROLE_ADMIN, authenticate_user, get_active_user
from services.intent import classify_intent, parse_workflow_pick
from services.question_log import (
    get_journey_report,
    log_bot_question,
    log_result_feedback,
    log_user_answer,
    log_user_opening,
)
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
from services.ai_analyze import analyze_process_description, coerce_publish_bundle
from services.workflow_validate import validate_registry, validate_workflow

app = FastAPI(title="Danışman AI")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
    same_site="lax",
)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class Message(BaseModel):
    conversation_id: str
    message: str


class ResultFeedback(BaseModel):
    conversation_id: str
    solved: bool


class LoginBody(BaseModel):
    username: str
    password: str


class NewWorkflowBody(BaseModel):
    code: str = Field(..., description="Dosya adı: ornek_akış")
    name: str = "Yeni süreç"
    clone_from: str | None = None


class AnalyzeProcessBody(BaseModel):
    description: str = Field(..., min_length=15, max_length=60000)


class PublishAIWorkflowBody(BaseModel):
    workflow: dict[str, Any]
    intent: dict[str, Any]


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


def _current_user(request: Request) -> dict[str, Any] | None:
    username = str(request.session.get("username") or "").strip()
    if not username:
        return None
    user = get_active_user(username)
    if not user:
        request.session.clear()
        return None
    return user


def _require_user(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Giriş gerekli.")
    return user


def _require_admin(request: Request) -> dict[str, Any]:
    user = _require_user(request)
    if user.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Bu alan sadece admin.")
    return user


def _login_redirect(next_path: str) -> RedirectResponse:
    safe_next = next_path if next_path.startswith("/") else "/"
    return RedirectResponse(url=f"/login?next={quote(safe_next)}", status_code=303)


def _redirect_by_role(user: dict[str, Any]) -> RedirectResponse:
    if user.get("role") == ROLE_ADMIN:
        return RedirectResponse(url="/admin", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.get("/login")
def login_page(request: Request, next: str = "/"):
    user = _current_user(request)
    if user:
        if next.startswith("/") and (user.get("role") == ROLE_ADMIN or next == "/"):
            return RedirectResponse(url=next, status_code=303)
        return _redirect_by_role(user)
    return FileResponse("static/login.html", media_type="text/html; charset=utf-8")


@app.post("/api/login")
def api_login(data: LoginBody, request: Request):
    user = authenticate_user(data.username.strip(), data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya şifre hatalı.")
    request.session.clear()
    request.session["username"] = user["username"]
    return {"ok": True, "user": user}


@app.post("/api/logout")
def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/api/me")
def api_me(request: Request):
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Giriş gerekli.")
    return {"user": user}


@app.get("/")
def index(request: Request):
    if not _current_user(request):
        return _login_redirect("/")
    return FileResponse("static/index.html", media_type="text/html; charset=utf-8")


@app.get("/admin")
def admin_page(request: Request):
    user = _current_user(request)
    if not user:
        return _login_redirect("/admin")
    if user.get("role") != ROLE_ADMIN:
        return RedirectResponse(url="/", status_code=303)
    return FileResponse("static/admin.html", media_type="text/html; charset=utf-8")


@app.get("/admin/ai-process")
def admin_ai_process_page(request: Request):
    user = _current_user(request)
    if not user:
        return _login_redirect("/admin/ai-process")
    if user.get("role") != ROLE_ADMIN:
        return RedirectResponse(url="/", status_code=303)
    return FileResponse("static/ai-process.html", media_type="text/html; charset=utf-8")


@app.get("/report")
def report_page(request: Request):
    user = _current_user(request)
    if not user:
        return _login_redirect("/report")
    if user.get("role") != ROLE_ADMIN:
        return RedirectResponse(url="/", status_code=303)
    return FileResponse("static/report.html", media_type="text/html; charset=utf-8")


@app.get("/api/report/journey")
def api_journey_report(
    request: Request,
    limit: int = 100,
    workflow_code: str | None = None,
    only_unsolved: bool = False,
):
    _require_admin(request)
    items = get_journey_report(
        limit=limit,
        workflow_code=workflow_code,
        only_unsolved=only_unsolved,
    )
    return {"items": items}


@app.get("/api/workflows")
def api_list_workflows(request: Request):
    _require_admin(request)
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


@app.post("/api/ai/analyze-process")
def api_ai_analyze_process(request: Request, body: AnalyzeProcessBody):
    _require_admin(request)
    try:
        return analyze_process_description(body.description)
    except RuntimeError as e:
        detail = str(e)
        if "OPENAI_API_KEY" in detail:
            raise HTTPException(status_code=503, detail=detail) from e
        raise HTTPException(status_code=502, detail=detail) from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=str(e) or "OpenAI isteği başarısız.",
        ) from e


@app.post("/api/ai/publish-workflow")
def api_ai_publish_workflow(request: Request, body: PublishAIWorkflowBody):
    _require_admin(request)
    wf, intent_row, err = coerce_publish_bundle(body.workflow, body.intent)
    if err:
        raise HTTPException(status_code=400, detail=err)
    code = wf["code"]
    try:
        save_workflow_file(code, wf)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    reg = load_registry()
    wfs = list(reg.get("workflows") or [])
    idx = next((i for i, w in enumerate(wfs) if w.get("code") == code), None)
    if idx is not None:
        wfs[idx] = {**wfs[idx], **intent_row}
    else:
        wfs.insert(0, intent_row)
    reg["workflows"] = wfs
    ok, verr = validate_registry(reg)
    if not ok:
        raise HTTPException(status_code=400, detail=verr)
    try:
        save_registry(reg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "code": code}


@app.get("/api/registry")
def api_get_registry(request: Request):
    _require_admin(request)
    return registry_workflows_newest_first(load_registry())


@app.put("/api/registry")
def api_put_registry(request: Request, data: dict = Body(...)):
    _require_admin(request)
    ok, err = validate_registry(data)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    try:
        save_registry(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/workflow/{code}")
def api_get_workflow(request: Request, code: str):
    _require_admin(request)
    try:
        return load_workflow_file(code)
    except OSError:
        raise HTTPException(status_code=404, detail="Akış bulunamadı.")


@app.put("/api/workflow/{code}")
def api_put_workflow(request: Request, code: str, data: dict = Body(...)):
    _require_admin(request)
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
def api_create_workflow(request: Request, body: NewWorkflowBody):
    _require_admin(request)
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
def api_delete_workflow(request: Request, code: str):
    _require_admin(request)
    if code not in list_workflow_files():
        raise HTTPException(status_code=404, detail="Yok.")
    delete_workflow_file(code)
    reg = load_registry()
    reg["workflows"] = [w for w in reg.get("workflows", []) if w.get("code") != code]
    save_registry(reg)
    return {"ok": True}


@app.post("/message")
def message(request: Request, data: Message):
    _require_user(request)
    conv = get_conversation(data.conversation_id)

    # Önceki görüşmede tüm sorular cevaplanmışsa oturumu kapat;
    # aksi halde yeni mesaj yanlışlıkla tekrar sonuç üretir (soru sormadan).
    # Kayıtlı workflow silinmiş / DB boşsa FileNotFoundError: oturumu sıfırla.
    if conv:
        try:
            _wf = load_workflow(conv["workflow"])
        except OSError:
            clear_conversation(data.conversation_id)
            conv = None
        else:
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


@app.post("/api/result-feedback")
def api_result_feedback(request: Request, data: ResultFeedback):
    _require_user(request)
    conv = get_conversation(data.conversation_id)
    workflow_code = conv.get("workflow") if isinstance(conv, dict) else None
    log_result_feedback(data.conversation_id, workflow_code, data.solved)
    return {"ok": True}
