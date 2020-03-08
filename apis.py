from requests import Session, exceptions
from diskcache import Cache

cache = Cache("./cache")

# TODO: add cache refreshing

s = Session()
s.headers = {"User-Agent": "WikiTagger/0.0 (alexzabbey@gmail.com) Python/Requests/3.8"}


def enter_wd_api(d):
    return d["query"]["pages"][list(d["query"]["pages"].keys())[0]]


def get_wp_fulltext(title):
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
def get_wdid_from_wp(title):
    params = {"action": "query", "prop": "pageprops", "titles": title, "format": "json"}
    res = s.get("https://he.wikipedia.org/w/api.php", params=params)
    res.raise_for_status()
    d = enter_wd_api(res.json())
    if d.get("pageprops", False):
        return d["pageprops"].get("wikibase_item", False)
    else:
        return False


def graphql_query(query):
    # posting to GraphQL server
    for i in range(3):
        try:
            res = s.post(
                "https://tools.wmflabs.org/tptools/wdql.php",
                json={"query": "{" + query + "}"},
            )
            res.raise_for_status()
            return res.json()
        except exceptions.HTTPError:
            print(f"GraphQL try {i}")
            continue


def instance_of(Q_list):
    query = ""
    for Q in Q_list:
        query += (
            f"""{Q}: item(id: "{Q}")"""
            + """ {statements(propertyIds: "P31") { mainsnak { ... on PropertyValueSnak { value { ... on Entity { id }}}}}}
            """
        )

    j = graphql_query(query)
    return {
        k: [i["mainsnak"]["value"]["id"] for i in j["data"][k]["statements"]]
        for k in j["data"].keys()
    }


def sparql_query(query, labels=False, without_roots=False):
    url = "https://query.wikidata.org/sparql"
    if without_roots:
        query = query.replace("*", "+")
    res = s.get(url, params={"query": query, "format": "json"})
    res.raise_for_status()
    j = res.json()
    var = [var for var in j["head"]["vars"] if "Label" not in var][0]
    if labels:
        result = [
            (d[var]["value"].split("/")[-1], d[var + "Label"]["value"])
            for d in j["results"]["bindings"]
        ]
    else:
        result = list(
            set([x[var]["value"].split("/")[-1] for x in j["results"]["bindings"]])
        )
    #     if without_roots:
    #         result = list(result - set(roots))
    return result


@cache.memoize()
def get_subclasses(roots, exclude=None):
    print("starting SPARQL query")
    # SPARQL
    if roots == None:
        return []

    def build_query(roots):
        return (
            "SELECT ?subclass WHERE { VALUES ?roots { "
            + " ".join(["wd:" + r for r in roots])
            + " } ?subclass wdt:P279* ?roots.}"
        )

    result = sparql_query(build_query(roots))
    if exclude:
        result = list(set(result) - set(sparql_query(build_query(exclude))))
    return result


def get_instance_of(q):
    params = {
        "action": "wbgetclaims",
        "entity": q,
        "property": "P31",
        "rank": "normal",
        "format": "json",
    }
    res = s.get("https://www.wikidata.org/w/api.php", params=params)
    res.raise_for_status()
    return [
        x["mainsnak"]["datavalue"]["value"]["id"] for x in res.json()["claims"]["P31"]
    ]


#     if d.get("pageprops", False):
#         return d["pageprops"].get("wikibase_item", False)
#     else:
#         return False
