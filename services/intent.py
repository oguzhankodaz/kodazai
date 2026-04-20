from services.normalizer import fold_tr_ascii
from services.workflow_store import load_registry


def _load_catalog() -> list:
    return load_registry().get("workflows", [])


def _fold_kw(k: str) -> str:
    """Registry anahtar kelimeleri Türkçe karakterli olabilir; kullanıcı metniyle aynı şekilde düzleştir."""
    if not k or not str(k).strip():
        return ""
    return fold_tr_ascii(str(k).strip())


def _strict_intent(text: str, catalog: list) -> str | None:
    for entry in catalog:
        st = entry.get("strict")
        if not st or not isinstance(st, dict):
            continue
        must = st.get("must_include_all") or []
        one = st.get("include_one_of") or []
        if must:
            ok = True
            for k in must:
                fk = _fold_kw(k)
                if not fk or fk not in text:
                    ok = False
                    break
            if not ok:
                continue
        if one:
            found = False
            for k in one:
                fk = _fold_kw(k)
                if fk and fk in text:
                    found = True
                    break
            if not found:
                continue
        if must or one:
            return entry["code"]
    return None


def _score_workflow(text: str, entry: dict) -> int:
    score = 0
    for kw in entry.get("keywords", []):
        fk = _fold_kw(kw)
        if fk and fk in text:
            score += 1
    if "ters" in text and "kayit" in text:
        score += 2
    return score


def classify_intent(text: str) -> dict:
    """
    Dönüş:
      { "kind": "direct", "intent": "..." }
      { "kind": "choose", "candidates": [ { "code", "label", "description" }, ... ] }
      { "kind": "unknown" }
    """
    text = fold_tr_ascii(text)
    catalog = _load_catalog()

    direct = _strict_intent(text, catalog)
    if direct:
        return {"kind": "direct", "intent": direct}

    scored = []
    for entry in catalog:
        s = _score_workflow(text, entry)
        if s > 0:
            scored.append(
                {
                    "code": entry["code"],
                    "label": entry.get("label", entry["code"]),
                    "description": entry.get("description", ""),
                    "score": s,
                }
            )

    scored.sort(key=lambda x: -x["score"])

    if not scored:
        return {"kind": "unknown"}

    best = scored[0]["score"]
    top = [c for c in scored if c["score"] == best]

    if len(top) == 1 and best >= 2:
        return {"kind": "direct", "intent": top[0]["code"]}

    pool = top if len(top) > 1 else scored[:3]
    if not pool:
        return {"kind": "unknown"}
    return {
        "kind": "choose",
        "candidates": [
            {
                "code": c["code"],
                "label": c["label"],
                "description": c["description"],
            }
            for c in pool
        ],
    }


WORKFLOW_PICK_PREFIX = "__workflow__:"


def parse_workflow_pick(message: str) -> str | None:
    m = message.strip()
    if m.startswith(WORKFLOW_PICK_PREFIX):
        return m[len(WORKFLOW_PICK_PREFIX) :].strip() or None
    return None


def detect_intent(text: str) -> str:
    r = classify_intent(text)
    if r["kind"] == "direct":
        return r["intent"]
    return "unknown"
