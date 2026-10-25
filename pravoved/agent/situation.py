# вид ситуации человека; по нему убираем нормы из соседних разделов (прокат для аренды офиса и т.п.)
SITUATIONS = {
    "arenda_nezhilogo": "аренда офиса, склада, здания, нежилого помещения (не прокат)",
    "arenda_veshchi": "аренда оборудования, транспорта, другого имущества между бизнесом/людьми (не прокат)",
    "prokat": "прокат: организация на короткий срок сдаёт потребителю вещь (велосипед, инструмент, авто)",
    "naem_zhilya": "съём или наём жилья: квартира, комната, дом",
    "potrebitel_tovar": "потребитель купил товар (возврат, брак, обмен, доставка)",
    "potrebitel_usluga": "потребитель заказал работу или услугу (ремонт, абонемент, курсы, перевозка)",
    "trud": "обычные трудовые отношения: зарплата, увольнение, отпуск, дисциплина",
    "trud_osobyj": "особая категория работника, названная в вопросе: беременная, до 18 лет, руководитель, совместитель, вахта, сезонный, надомник, дистанционный, педагог, иностранец",
    "trud_sever": "работа в районах Крайнего Севера или приравненных местностях, названных в вопросе",
    "drugoe": "всё остальное (заём, дарение, купля-продажа между гражданами, не по этой базе)",
}

# режим раздела -> в каких ситуациях его нормы подходят; режимов нет в списке - подходят всегда
ALLOWED = {
    "prokat": {"prokat"},
    "arenda_ts": {"arenda_veshchi"},
    "arenda_zdanij": {"arenda_nezhilogo"},
    "arenda_predpr": set(),
    "lizing": set(),
    "naem_zhilya": {"naem_zhilya"},
    "arenda_obshchaya": {"arenda_nezhilogo", "arenda_veshchi", "prokat", "naem_zhilya"},
    "trud_sever": {"trud_sever"},
    "trud_osobyj": {"trud_osobyj", "trud_sever"},
}
# эти разделы только опускаем вниз, а не выбрасываем
SOFT = {"potrebitel_tovar", "potrebitel_usluga"}


def fits(regime, situation):
    if not regime:
        return True
    if regime in SOFT:
        return regime == situation or situation not in SOFT
    return situation in ALLOWED.get(regime, {situation})


def filter_hits(hits, situation):
    """-> (подходящие, отброшенные). Мягкие разделы идут в конец, жёстко неподходящие отбрасываются."""
    if situation not in SITUATIONS or situation == "drugoe":
        return hits, []
    good, soft, dropped = [], [], []
    for h in hits:
        if h.regime in SOFT and not fits(h.regime, situation):
            soft.append(h)
        elif fits(h.regime, situation):
            good.append(h)
        else:
            dropped.append(h)
    # если отбросили всё, лучше оставить как было
    if not good and not soft:
        return hits, []
    return good + soft, dropped


def describe(situation):
    return SITUATIONS.get(situation, "")
