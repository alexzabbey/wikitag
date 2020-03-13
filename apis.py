from requests import Session, exceptions
from diskcache import Cache
from typing import Union, Optional
from pprint import pprint
from itertools import groupby
import re

cache = Cache("./cache")

# TODO: add cache refreshing

s = Session()
s.headers = {"User-Agent": "WikiTagger/0.0 (alexzabbey@gmail.com) Python/Requests/3.8"}


def enter_wd_api(d: dict) -> dict:
    return d["query"]["pages"][list(d["query"]["pages"].keys())[0]]


def get_wp_fulltext(title: str) -> dict:
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "format": "json",
        "rvprop": "content",
        "rvslots": "main",
    }
    res = s.get("https://he.wikipedia.org/w/api.php", params=params)
    res.raise_for_status()
    print(f"got full wikipedia text from page {title}")
    return enter_wd_api(res.json())["revisions"][0]["slots"]["main"]["*"]


@cache.memoize()
def get_wdid_from_wp(title: str) -> Union[str, bool]:
    params = {"action": "query", "prop": "pageprops", "titles": title, "format": "json"}
    res = s.get("https://he.wikipedia.org/w/api.php", params=params)
    res.raise_for_status()
    d = enter_wd_api(res.json())
    if d.get("pageprops", False):
        return d["pageprops"].get("wikibase_item", False)
    else:
        return False


def sparql_query(query: str) -> list:
    print("running sparql query")
    url = "https://query.wikidata.org/sparql"
    try:
        res = s.get(
            url, params={"query": re.sub(r"\s+", " ", query), "format": "json"}
        )  # shorter query
        res.raise_for_status()
        j = res.json()
    except exceptions.HTTPError as e:
        print(e.response.status_code)
        print(query)
        raise exceptions.HTTPError

    result = j["results"]["bindings"]
    for d in result:
        for k, v in d.items():
            d[k] = v["value"].split("/")[-1]
    return result


# @cache.memoize()
def get_subclasses(roots: Optional[list], exclude: bool = None) -> list:
    if roots == None:
        return []

    def build_query(roots):
        return (
            "SELECT ?subclass WHERE { VALUES ?roots { "
            + " ".join(["wd:" + r for r in roots])
            + " } ?subclass wdt:P279* ?roots.}"
        )

    result = [x["subclass"] for x in sparql_query(build_query(roots))]
    if exclude:
        exclude_list = [x["subclass"] for x in sparql_query(build_query(exclude))]
        result = list(set(result) - set(exclude_list))
    return result


def get_instance_of(Q_list: list) -> dict:
    query = (
        "SELECT ?entity ?class WHERE { VALUES ?entity {"
        + "\n".join(["wd:" + q for q in Q_list])
        + "} ?entity wdt:P31 ?class. }"
    )

    result = sparql_query(query)
    res = {
        k: [i["class"] for i in list(g)]
        for k, g in groupby(result, key=lambda x: x["entity"])
    }

    return res
