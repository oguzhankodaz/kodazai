_TR_ASCII = {
    "ı": "i",
    "İ": "i",
    "ğ": "g",
    "ş": "s",
    "ü": "u",
    "ö": "o",
    "ç": "c",
}


def fold_tr_ascii(text: str) -> str:
    """Türkçe büyük İ / birleşik nokta sorunları olmadan ASCII'ye yakın metin (intent eşleştirme için)."""
    normalized = text.strip().replace("İ", "i").lower()
    for tr, en in _TR_ASCII.items():
        normalized = normalized.replace(tr, en)
    return normalized


def normalize_answer(field: str, text: str) -> str:
    normalized = fold_tr_ascii(text)

    if field == "piyasa_tipi":
        if normalized in ["ic", "ic piyasa", "iç", "iç piyasa", "yurtici"]:
            return "ic"
        if normalized in ["dis", "dis piyasa", "dış", "dış piyasa", "ihracat"]:
            return "dis"

    if field in [
        "gib_durumu",
        "fatura_durumu",
        "siparis_hesap_kodu_var_mi",
        "bilgiler_bulundu_mu",
    ]:
        if normalized in ["evet", "var", "gitti", "kesildi", "olustu", "oldu"]:
            return "evet"
        if normalized in ["hayir", "yok", "gitmedi", "kesilmedi", "olusmadi", "olmadi"]:
            return "hayir"

    return normalized