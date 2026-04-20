def validate_workflow(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Geçersiz JSON nesnesi."
    if "code" not in data or not str(data["code"]).strip():
        return False, "'code' zorunlu."
    if "name" not in data:
        return False, "'name' zorunlu."
    if "questions" not in data or not isinstance(data["questions"], list):
        return False, "'questions' bir dizi olmalı."
    if "rules" not in data or not isinstance(data["rules"], list):
        return False, "'rules' bir dizi olmalı."

    fields = []
    for i, q in enumerate(data["questions"]):
        if not isinstance(q, dict):
            return False, f"Soru {i} geçersiz."
        for k in ("field", "question", "options"):
            if k not in q:
                return False, f"Soru {i}: '{k}' eksik."
        if not isinstance(q["options"], list) or len(q["options"]) < 1:
            return False, f"Soru {i}: 'options' en az bir değer içermeli."
        fields.append(q["field"])

    if not fields:
        if data["rules"]:
            return (
                False,
                "Henüz soru yokken kural eklenemez; önce soru ekleyin veya kuralları boşaltın.",
            )
        return True, ""

    for i, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict):
            return False, f"Kural {i} geçersiz."
        if "if" not in rule or not isinstance(rule["if"], dict):
            return False, f"Kural {i}: 'if' bir nesne olmalı."
        if "result" not in rule or not isinstance(rule["result"], dict):
            return False, f"Kural {i}: 'result' bir nesne olmalı."
        rif = rule["if"]
        for fk in rif.keys():
            if fk not in fields:
                return False, f"Kural {i}: 'if' içinde bilinmeyen alan '{fk}'."

    for i, q in enumerate(data["questions"]):
        show_if = q.get("show_if")
        if not show_if:
            continue
        if not isinstance(show_if, dict):
            return False, f"Soru {i}: 'show_if' bir nesne olmalı."
        for fk in show_if.keys():
            if fk not in fields:
                return False, f"Soru {i}: show_if'te bilinmeyen alan '{fk}'."
            if fk == q["field"]:
                return False, f"Soru {i}: show_if kendi alanına referans veremez."

    return True, ""


def validate_registry(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Geçersiz registry."
    wfs = data.get("workflows")
    if not isinstance(wfs, list):
        return False, "'workflows' bir dizi olmalı."
    codes = set()
    for i, w in enumerate(wfs):
        if not isinstance(w, dict):
            return False, f"Kayıt {i} geçersiz."
        code = str(w.get("code", "")).strip()
        if not code:
            return False, f"Kayıt {i}: 'code' zorunlu."
        if code in codes:
            return False, f"Yinelenen kod: {code}"
        codes.add(code)
        if not w.get("label"):
            return False, f"{code}: 'label' zorunlu."
        kws = w.get("keywords")
        if not isinstance(kws, list) or len(kws) < 1:
            return False, f"{code}: en az bir 'keywords' girin."
    return True, ""
