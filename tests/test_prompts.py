from pravoved.agent import prompts


def test_base_description_lists_new_documents():
    for text in (prompts.GRADE_SYSTEM, prompts.REFUSAL):
        assert "КоАП" in text
        assert "657" in text
        assert "924" in text
    assert "2463" not in prompts.REFUSAL


def test_answer_prompt_has_base_date():
    from datetime import date
    base = prompts.BASE_DATE.format(date="24.10.2026")
    system = prompts.ANSWER_SYSTEM.format(today="25.10.2026", base_date=base)
    assert "24.10.2026" in system and "25.10.2026" in system
    assert "{" not in system
