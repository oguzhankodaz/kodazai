"""
Kullanıcı mesajındaki kelimelerin geçtiği akışları bulur (soru metinleri, başlıklar, registry).
"""
import re
from typing import Any

from services.normalizer import fold_tr_ascii
from services.workflow_store import list_workflow_files, load_registry, load_workflow_file

_MAX_RESULTS = 25
_MIN_TOKEN_LEN = 3


def _tokens(q: str) -> list[str]:
    q = fold_tr_ascii(q).strip()
    if len(q) < _MIN_TOKEN_LEN:
        return []
    parts = re.split(r"[\s,;.]+", q)
    return [p for p in parts if len(p) >= _MIN_TOKEN_LEN]


def _blob_for_workflow(code: str, meta: dict[str, Any] | None, w: dict[str, Any]) -> str:
    """
    Yalnızca 'konu tanımı' metinleri: intent + akış adı + soru/cevap şıkları.
    Kural sonuçları (adımlar, uyarılar) DAHİL DEĞİL — aksi halde 'muhasebe' gibi
    sık kelimeler her akışta geçtiği için liste şişiyor.
    """
    parts = [
        meta.get("label", "") if meta else "",
        meta.get("description", "") if meta else "",
        " ".join(meta.get("keywords", [])) if meta else "",
        code.replace("_", " "),
        w.get("name", ""),
        w.get("code", ""),
    ]
    for qu in w.get("questions", []):
        parts.append(qu.get("question", ""))
        parts.extend(qu.get("options", []) or [])
        parts.append(qu.get("field", "") or "")
    return fold_tr_ascii(" ".join(parts))


def search_matching_topics(raw: str) -> list[dict[str, str]]:
    """
    Mesajdeki her token (>=3 karakter), birleştirilmiş metinde alt dizgi olmalı (hepsi AND).
    Dönüş: { code, label, description } listesi, skora göre azalan.
    """
    toks = _tokens(raw)
    if not toks:
        return []

    reg = load_registry()
    by_code: dict[str, dict] = {x["code"]: x for x in reg.get("workflows", [])}
    scored: list[tuple[int, dict[str, str]]] = []

    for code in list_workflow_files():
        meta = by_code.get(code)
        try:
            w = load_workflow_file(code)
        except OSError:
            continue

        if not meta:
            meta = {
                "code": code,
                "label": w.get("name", code),
                "description": "",
                "keywords": [],
            }

        blob = _blob_for_workflow(code, meta, w)
        if not all(t in blob for t in toks):
            continue

        score = sum(blob.count(t) * len(t) for t in toks)
        scored.append(
            (
                score,
                {
                    "code": code,
                    "label": str(meta.get("label", w.get("name", code))),
                    "description": str(meta.get("description", "")),
                },
            )
        )

    scored.sort(key=lambda x: -x[0])
    out = [item[1] for item in scored[:_MAX_RESULTS]]
    return out
