from services.workflow_store import load_workflow_file


def load_workflow(code):
    return load_workflow_file(code)


def _question_applies(q: dict, answers: dict) -> bool:
    """show_if yoksa her zaman sorulur; varsa önceki cevaplarla eşleşmeli."""
    show_if = q.get("show_if")
    if not show_if:
        return True
    if not isinstance(show_if, dict):
        return True
    for fk, fv in show_if.items():
        if answers.get(fk) != fv:
            return False
    return True


def get_next_question(workflow, answers):
    """
    Soru sırası korunur; cevabı olmayan ilk uygun soru döner.
    show_if koşulu sağlanmıyorsa o soru atlanır (hiç sorulmaz, cevap da istenmez).
    """
    for q in workflow["questions"]:
        field = q["field"]
        if field in answers:
            continue
        if not _question_applies(q, answers):
            continue
        return q
    return None


def match_rule(conditions, answers):
    for k, v in conditions.items():
        if answers.get(k) != v:
            return False
    return True


def resolve(workflow, answers):
    for rule in workflow["rules"]:
        if match_rule(rule["if"], answers):
            return rule["result"]

    return workflow.get(
        "default_result",
        {
            "title": "Net sonuç bulunamadı",
            "steps": ["Manuel kontrol gerekli"],
        },
    )
