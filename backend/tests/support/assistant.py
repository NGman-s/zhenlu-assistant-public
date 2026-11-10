from app.providers.assistant import AssistantResult


class MockAssistantProvider:
    """Extractive demo, never a medical inference or a pretend model answer."""
    name = "mock-record-assistant-v1"
    is_mock = True

    def answer(self, question: str, context: dict) -> AssistantResult:
        if any(word in question for word in ("诊断", "治疗", "建议吃", "应该吃", "开药", "其他患者", "其他病人")):
            return AssistantResult("out_of_scope", ())
        keywords = {
            "chief_complaint": ("主诉",), "present_illness": ("症状", "现病史"),
            "past_history": ("病史", "既往"), "medication_history": ("用药", "服药", "药物", "吃过"),
            "allergy_history": ("过敏",),
        }
        selected = [key for key, words in keywords.items() if any(w in question for w in words)]
        summary = any(w in question for w in ("汇总", "总结", "重点", "缺失", "未提及"))
        answers = []
        for evidence in context["evidence"]:
            if evidence["kind"] == "field" and (summary or evidence["field_key"] in selected):
                if ("缺失" in question or "未提及" in question) and evidence["value"] != "未提及":
                    continue
                answers.append({"text": f'{evidence["label"]}：{evidence["value"]}', "evidence_ids": [evidence["id"]]})
        return AssistantResult("answered" if answers else "insufficient", tuple(answers))
