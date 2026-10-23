import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("build", "search"):
        print('использование: python -m pravoved.retrieval build | search "вопрос"')
        return
    if sys.argv[1] == "build":
        from .index import build
        build()
        return
    from .search import search
    from .store import close_client
    query = " ".join(sys.argv[2:])
    for hit in search(query):
        part = " ч. " + hit.part if hit.part else ""
        print("%.4f  %s%s  %s" % (hit.score, hit.citation, part, hit.title))
        print("        " + hit.text[:150].replace("\n", " "))


main()
