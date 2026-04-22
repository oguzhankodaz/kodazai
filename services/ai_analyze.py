"""OpenAI ile süreç açıklamasından akış JSON + intent satırı üretimi."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from services.workflow_validate import validate_registry, validate_workflow

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _normalize_code(raw: str) -> str:
    s = (raw or "").strip().lower().replace("-", "_")
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "surec"
    if not s[0].isalpha():
        s = "s_" + s
    if len(s) > 63:
        s = s[:63]
    if not _CODE_RE.match(s):
        s = "surec"
    return s


def _normalize_workflow(data: dict[str, Any]) -> dict[str, Any]:
    code = _normalize_code(str(data.get("code") or ""))
    data = dict(data)
    data["code"] = code
    data["name"] = str(data.get("name") or code).strip() or code
    qs: list[dict[str, Any]] = []
    for q in data.get("questions") or []:
        if not isinstance(q, dict):
            continue
        field = re.sub(r"[^a-z0-9_]+", "_", str(q.get("field") or "alan").lower()).strip("_")
        if not field or not field[0].isalpha():
            field = "alan_" + str(len(qs) + 1)
        opts = q.get("options") or []
        if isinstance(opts, str):
            opts = [x.strip() for x in re.split(r"[,;\n]", opts) if x.strip()]
        opts = [str(o).strip() for o in opts if str(o).strip()]
        if not opts:
            opts = ["evet", "hayır"]
        item: dict[str, Any] = {
            "field": field[:64],
            "question": str(q.get("question") or "").strip() or field,
            "options": opts,
        }
        if q.get("type"):
            item["type"] = str(q["type"])
        si = q.get("show_if")
        if isinstance(si, dict) and si:
            item["show_if"] = {str(k): str(v) for k, v in si.items()}
        qs.append(item)

    fields = {q["field"] for q in qs}
    for q in qs:
        si = q.get("show_if")
        if not isinstance(si, dict):
            continue
        clean_si: dict[str, str] = {}
        for k, v in si.items():
            fk = str(k)
            if fk in fields and fk != q["field"]:
                clean_si[fk] = str(v)
        if clean_si:
            q["show_if"] = clean_si
        else:
            q.pop("show_if", None)

    rules_out: list[dict[str, Any]] = []
    for r in data.get("rules") or []:
        if not isinstance(r, dict):
            continue
        rif = r.get("if")
        if not isinstance(rif, dict):
            rif = {}
        if_clean: dict[str, str] = {}
        for k, v in rif.items():
            fk = str(k)
            if fk not in fields:
                continue
            if_clean[fk] = str(v)
        res = r.get("result")
        if not isinstance(res, dict):
            res = {}
        if not if_clean:
            continue
        steps = res.get("steps") or []
        if isinstance(steps, str):
            steps = [x.strip() for x in steps.split("\n") if x.strip()]
        steps = [str(s).strip() for s in steps if str(s).strip()]
        if not steps:
            steps = ["İşlem tamamlandı."]
        rules_out.append(
            {
                "if": if_clean,
                "result": {
                    "title": str(res.get("title") or "Sonuç").strip() or "Sonuç",
                    "steps": steps,
                    "warning": str(res.get("warning") or "").strip(),
                },
            }
        )
    data["rules"] = rules_out

    dr = data.get("default_result")
    if not isinstance(dr, dict):
        dr = {}
    dsteps = dr.get("steps") or []
    if isinstance(dsteps, str):
        dsteps = [x.strip() for x in dsteps.split("\n") if x.strip()]
    dsteps = [str(s).strip() for s in dsteps if str(s).strip()]
    if not dsteps:
        dsteps = ["Bu cevap kombinasyonu için kural ekleyin."]
    data["default_result"] = {
        "title": str(dr.get("title") or "Tanımsız kombinasyon").strip() or "Tanımsız kombinasyon",
        "steps": dsteps,
        "warning": str(dr.get("warning") or "").strip(),
    }
    return data


def _normalize_intent(intent: dict[str, Any], code: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": code,
        "label": str(intent.get("label") or code).strip() or code,
        "description": str(intent.get("description") or "").strip(),
        "keywords": intent.get("keywords") or [code],
    }
    if not isinstance(out["keywords"], list):
        out["keywords"] = [str(out["keywords"])]
    out["keywords"] = [str(k).strip() for k in out["keywords"] if str(k).strip()]
    if not out["keywords"]:
        out["keywords"] = [code]
    cat = intent.get("category")
    if cat is not None and str(cat).strip():
        out["category"] = str(cat).strip()[:128]
    st = intent.get("strict")
    if isinstance(st, dict):
        must = [str(x).strip() for x in (st.get("must_include_all") or []) if str(x).strip()]
        one = [str(x).strip() for x in (st.get("include_one_of") or []) if str(x).strip()]
        if must or one:
            out["strict"] = {"must_include_all": must, "include_one_of": one}
    return out


SYSTEM_PROMPT = """Sen bir iş süreci modelleme asistanısın. Kullanıcının doğal dilde anlattığı süreci,
aşağıdaki kurallara uygun TEK bir JSON nesnesi olarak döndüreceksin. Yanıtta başka metin, markdown veya açıklama yok; yalnızca JSON.

Çıkış şeması (anahtarlar tam olarak bunlar olmalı):
{
  "workflow": { ... },
  "intent": { ... }
}

--- workflow nesnesi ---
- "code": küçük harf, rakam, alt çizgi; harf ile başlasın (ör. irsaliye_iptal). Akışın benzersiz kimliği.
- "name": kullanıcıya gösterilecek Türkçe süreç başlığı.
- "questions": sıralı dizi. Her öğe:
  - "field": makine adı (ör. fatura_var_mi), sorular arasında benzersiz.
  - "question": kullanıcıya sorulacak tam cümle.
  - "options": dizi; her eleman tam eşleşecek cevap metni (ör. ["evet","hayır"] veya ["Evet","Hayır"] — tutarlı ol).
  - İsteğe bağlı "show_if": { "onceki_alan": "tam olarak o sorunun seçeneklerinden biri" } — yalnızca önceki cevap bu değerken bu soru sorulsun.
- "rules": her kural { "if": { "alan": "cevap değeri", ... }, "result": { "title": "...", "steps": ["adım1", ...], "warning": "" } }
  - "if" en az bir alan içermeli; boş "if" {} kullanma.
  - "if" içinde yalnızca o kombinasyonu ayırt etmek için gereken alanlar olsun; tüm alanları doldurmak zorunda değilsin.
  - Her soru alanı için olası cevaplara göre tüm anlamlı kombinasyonları mümkün olduğunca kapsa; kalanlar default_result ile kalabilir.
- "default_result": { "title": "...", "steps": ["..."], "warning": "" } — hiçbir kural eşleşmezse.

--- intent nesnesi (sohbette akışı bulmak için; workflow ile aynı "code") ---
- "code": workflow.code ile AYNI olmalı.
- "label": konu listesinde kısa başlık.
- "description": bir cümlelik özet (boş string olabilir).
- "category": isteğe bağlı kısa etiket veya boş string.
- "keywords": dizi; Türkçe anahtar kelimeler ve eş anlamlılar (en az 3-6 öğe öner).
- "strict": isteğe bağlı { "must_include_all": ["..."], "include_one_of": ["..."] } — kullanıcı mesajında eşzamanlı geçmesi gerekenler ve/veya en az birinin geçmesi gerekenler. Gerek yoksa her iki listeyi de boş dizi ver veya "strict" anahtarını hiç kullanma.

Kurallar:
- JSON geçerli olsun; çift tırnak kullan; son öğede virgül olmasın.
- Soru ve kural sayısını süreç karmaşıklığına göre seç; abartılı yüzlerce kural üretme, ama işi anlamlı kapsa.
"""


def _openai_chat_completion(messages: list[dict[str, str]], model: str, api_key: str) -> str:
    """Chat Completions REST; yalnızca standart kütüphane (ek paket yok)."""
    url = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0.25,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {e.code}: {body[:800]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenAI bağlantı hatası: {e}") from e

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI yanıtında choices yok.")
    msg = (choices[0].get("message") or {}) if isinstance(choices[0], dict) else {}
    return str(msg.get("content") or "").strip()


def analyze_process_description(user_text: str) -> dict[str, Any]:
    """
    OpenAI'dan workflow + intent döner.
    Dönüş: workflow, intent, validation_ok, validation_error (workflow doğrulaması)
    """
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY tanımlı değil.")

    model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
    raw = _openai_chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Aşağıdaki iş sürecini modelle:\n\n" + user_text.strip()},
        ],
        model=model,
        api_key=key,
    )
    if not raw:
        raise RuntimeError("Model boş yanıt döndü.")

    try:
        payload = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model geçersiz JSON döndü: {e}") from e

    wf = payload.get("workflow")
    intent = payload.get("intent")
    if not isinstance(wf, dict) or not isinstance(intent, dict):
        raise RuntimeError("Yanıtta 'workflow' ve 'intent' nesneleri bekleniyor.")

    wf = _normalize_workflow(wf)
    code = wf["code"]
    intent = _normalize_intent(intent, code)
    intent["code"] = code

    ok, err = validate_workflow(wf)
    reg_probe = {"version": 1, "workflows": [intent]}
    ok_r, err_r = validate_registry(reg_probe)

    validation_error = ""
    if not ok:
        validation_error = err
    elif not ok_r:
        validation_error = f"Intent: {err_r}"

    return {
        "workflow": wf,
        "intent": intent,
        "validation_ok": bool(ok and ok_r),
        "validation_error": validation_error,
    }


def coerce_publish_bundle(workflow: dict[str, Any], intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    """İstemciden gelen taslakları normalize eder ve doğrular. Hata mesajı boşsa başarılıdır."""
    wf = _normalize_workflow(dict(workflow))
    code = wf["code"]
    intent_n = _normalize_intent(dict(intent), code)
    intent_n["code"] = code
    if str(intent_n.get("code")) != str(wf.get("code")):
        return wf, intent_n, "intent.code ile workflow.code eşleşmiyor."
    ok, err = validate_workflow(wf)
    if not ok:
        return wf, intent_n, err
    ok_r, err_r = validate_registry({"version": 1, "workflows": [intent_n]})
    if not ok_r:
        return wf, intent_n, err_r
    return wf, intent_n, ""
