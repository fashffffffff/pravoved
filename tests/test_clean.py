from pravoved.agent.clean import drop_repeats, strip_marks


def test_strip_marks_collects_articles():
    text = "Заявите по статье 333 [не подтверждено источниками] и ст. 395 ГК РФ [не подтверждено источниками]. Срок [инструмент]."
    clean, names = strip_marks(text)
    assert clean == "Заявите по статье 333 и ст. 395 ГК РФ. Срок."
    assert names == ["статье 333", "ст. 395 ГК РФ"]


def test_drop_repeated_lines_and_sentences():
    text = ("Срок отсчитывается со следующего дня после передачи товара [1].\n"
            "Почему:\n"
            "* Срок отсчитывается со следующего дня после передачи товара.\n"
            "1. Подайте требование письменно. Срок отсчитывается со следующего дня после передачи товара.")
    out = drop_repeats(text).split("\n")
    assert out[0].startswith("Срок отсчитывается")
    assert "Почему:" in out
    assert len(out) == 3 or out[-1] == "1. Подайте требование письменно."


def test_numbered_steps_are_kept():
    text = "Что делать:\n1. Проверьте договор: указана ли там дата окончания аренды [3].\n2. Посмотрите, есть ли пункт об отказе от аренды."
    assert drop_repeats(text) == text


def test_marker_only_lines_are_removed():
    text = "Вывод тут, и он достаточно длинный для проверки повторов.\n* \n* Вывод тут, и он достаточно длинный для проверки повторов.\nНиже."
    assert drop_repeats(text) == "Вывод тут, и он достаточно длинный для проверки повторов.\nНиже."
