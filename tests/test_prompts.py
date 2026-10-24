from pravoved.agent import prompts


def test_base_description_lists_new_documents():
    for text in (prompts.GRADE_SYSTEM, prompts.REFUSAL):
        assert "КоАП" in text
        assert "657" in text
        assert "924" in text
    assert "2463" not in prompts.REFUSAL
