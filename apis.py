from requests import Session, exceptions
from typing import Union, Optional
from pprint import pprint
from itertools import groupby
import re, logging

# cache = Cache("./cache")

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
    logging.info(f"got full wikipedia text from page {title}")
    try:
        return enter_wd_api(res.json())["revisions"][0]["slots"]["main"]["*"]
    except IndexError:
        logging.info(f"whoops, it seems like {title} is not a wikipedia page")
        raise Exception(f"whoops, it seems like {title} is not a wikipedia page")


def sparql_query(query: str) -> list:
    logging.debug(f"running sparql query:\n{query}")
    url = "https://query.wikidata.org/sparql"
    try:
        res = s.get(
            url, params={"query": re.sub(r"\s+", " ", query), "format": "json"}
        )  # shorter query
        res.raise_for_status()
        j = res.json()
    except exceptions.HTTPError as e:
        logging.info(query)
        logging.info(f"raised a HTTP {e.response.status_code} error")
        raise exceptions.HTTPError

    result = j["results"]["bindings"]
    for d in result:
        for k, v in d.items():
            d[k] = v["value"].split("/")[-1]
    return result

