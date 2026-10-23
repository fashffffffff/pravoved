import re

import snowballstemmer
from rank_bm25 import BM25Okapi

stemmer = snowballstemmer.stemmer("russian")

# бытовые вопросы полны служебных слов, без них bm25 цепляется за мусор
STOPWORDS = set(
    "и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне "
    "было вот от меня еще нет о из ему теперь когда даже ну ли если уже или ни быть был него до вас "
    "вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам "
    "чтоб без будто чего раз тоже себе под будет тогда кто этот того потому этого какой совсем ним "
    "здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех можно при два об другой "
    "хоть после над больше тот через эти нас про всего них какая много три эту этой перед чуть том "
    "такой им более всегда конечно между это который которых которые которой которого".split()
)


def tokenize(text):
    words = re.findall(r"[а-яёa-z0-9]+", text.lower().replace("ё", "е"))
    return stemmer.stemWords([w for w in words if w not in STOPWORDS])


class BM25Index:
    def __init__(self, units):
        self.units = units
        self.bm25 = BM25Okapi([tokenize((u["title"] + " ") * 3 + u["text"]) for u in units])

    def search(self, query, k):
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [(self.units[i]["id"], float(scores[i])) for i in order if scores[i] > 0]
