import re, os, pickle, json, argparse, logging
from yaml import load, Loader
from requests import Session, exceptions
import pandas as pd
import mwparserfromhell as mwp
import wikitextparser as wtp
from more_itertools import split_when, split_at, chunked
from yap_tools import *
from apis import *
from helpers import *
from hebtokenizer import tokenize
from pprint import pprint
from typing import Dict, Tuple, List
from operator import itemgetter

# TODO:
# finish logging
# what should happen with tags
# add default "O"s if no entity was found in create_query()
# check all pages first?
# multiprocessing?
# append to csv instead of concating, in case it stops in the middle
# better tokenizer
# yap integration
# CONFIG options override json or not in cache_update
# tests

# FIXME: no such page error


WikiCode = mwp.wikicode.Wikicode
WikiLink = mwp.nodes.wikilink.Wikilink
DEBUG = False


def parse_wiki_page(page_title: str) -> WikiCode:
    wiki = wtp.parse(get_wp_fulltext(page_title))
    # remove files and categories
    for l in wiki.wikilinks:
        if l.title.startswith("קטגוריה:") or l.title.startswith("קובץ:"):
            del l[:]
    # remove extrenal links section
    for sec in wiki.sections[1:]:
        if "קישורים חיצוניים" in sec.title:
            del sec[:]
        else:
            del sec.title
    # remove lists
    for l in wiki.get_lists():
        del l[:]
    # remove templates and tables
    for x in ["templates", "tables"]:
        for attr in getattr(wiki, x):
            del attr[:]
    # replace tags with text
    for tag in wiki.get_tags():
        print(tag)
        print(tag.name)
    # for x in wiki.filter_tags():
    #     index = wiki.index(x)
    #     wiki.remove(x)
    #     wiki.insert(index, x.contents)

    print("finished parsing wiki page")
    return mwp.parse(wiki.string)


def basic_tag_prep() -> dict:
    with open("tags.yaml", "r", encoding="utf-8") as f:
        tags = load(f, Loader=Loader)
    for k, v in tags.items():
        if type(v) == list:
            tags[k] = {"include": v, "exclude": None, "not": None}
        else:
            tags[k].setdefault("exclude", None)
            tags[k].setdefault("not", None)
    return tags


def create_query(chunk: List[str], tags: dict, debug: bool = False):
    # wp_title -> wdid -> instance -> tag
    # ?i = item, ?ti = title, ?cl = class, ?t = tag ?sc = superclass, ?sl = sitelink
    return f"""SELECT {"?ti ?clLabel ?t" if debug else "?t ?ti"} (COUNT(?sc) AS ?c) WHERE {{
        VALUES ?ti {{ {" ".join([f'"{title}"@he' for title in chunk])} }}
        VALUES ?sc {{ { " ".join(["wd:"+x for x in  sum([v["include"] for v in tags.values()], [])])} }}
        ?sl schema:about ?i; 
            schema:isPartOf <https://he.wikipedia.org/>;
            schema:name ?ti.
        {"?i wdt:P31 ?cl. ?cl wdt:P279* ?sc." if debug else "?i wdt:P31/wdt:P279* ?sc."}
        BIND(COALESCE( {", ".join(["IF(" + " || ".join([f"?sc = wd:{q}" for q in v["include"]]) + f', "{k}", 1/0)' for k, v in tags.items()]) } ) AS ?t).
        {'SERVICE wikibase:label { bd:serviceParam wikibase:language "en".}' if debug else '' } }}
        GROUP BY {"?ti ?clLabel ?t" if debug else "?ti ?t"}"""


def get_cache() -> Dict:
    if not os.path.isfile("tagged_titles_cache.json"):
        with open("tagged_titles_cache.json", "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)
    with open("tagged_titles_cache.json", "r") as f:
        return json.load(f)


def cache_update(new: Dict, override: bool = True):
    new = {**get_cache(), **new} if override else {**new, **get_cache()}
    with open("tagged_titles_cache.json", "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)


def query_wikidata(query_titles: List, tags: Dict, debug: bool = DEBUG):
    tagged_titles, results = {}, []
    for chunk in list(chunked(query_titles, 20)):
        try:
            results += sparql_query(create_query(chunk, tags, debug))
        except exceptions.HTTPError:
            for minichunk in list(chunked(chunk, 5)):
                results += sparql_query(create_query(minichunk, tags, debug))
    if debug:
        pd.DataFrame(results).to_csv(
            "wikidata_query_results.csv", index=False, encoding="utf-8-sig"
        )
    for k, g in groupby(results, key=lambda x: x["ti"]):
        tagged_titles[k] = max(
            {x["t"]: x["c"] for x in list(g)}.items(), key=itemgetter(1)
        )[0]
    return tagged_titles


def get_titles(wiki: WikiCode, tags: dict):
    tt_cache = get_cache()
    titles = [str(l.title) for l in wiki.filter_wikilinks()]
    tagged_titles = {t: tt_cache[t] for t in titles if t in tt_cache.keys()}
    query_titles = [
        t.replace('"', '\\"') for t in titles if t not in tagged_titles.keys()
    ]
    tagged_titles.update(query_wikidata(query_titles, tags))
    cache_update(tagged_titles)
    return tagged_titles


@timing
def title_to_tag(wiki: WikiCode, tags: dict, debug: bool = DEBUG) -> pd.DataFrame:
    tagged_titles = get_titles(wiki, tags)

    def tag_wikilink(wl: WikiLink) -> Tuple[str, str]:
        tagged_list = []
        tag = tagged_titles.get(str(wl.title), "O")
        text = str(wl.text).split() if wl.text else str(wl.title).split()
        tags = (
            [f"B-{tag}"] + [f"I-{tag}"] * len(text) if tag != "O" else [tag] * len(text)
        )
        res = list(zip(text, tags))
        return res

    final = []
    for n in wiki.nodes:
        if isinstance(n, WikiLink):
            final += tag_wikilink(n)
        else:
            for x in n.split():
                final.append((x, "O"))
    final_df = pd.DataFrame(final, columns=["untokenized_word", "tag"])
    return final_df


def tokenize_and_split_df(df: pd.DataFrame) -> List[Tuple[str, str, str]]:
    df["untokenized_word"] = df["untokenized_word"].apply(tokenize)
    df = df.explode("untokenized_word")
    df[["word", "token"]] = pd.DataFrame(
        df["untokenized_word"].tolist(), index=df.index
    )
    df = df[["word", "tag", "token"]].reset_index(drop=True)
    return [[y for y in x if y[1] != "O"] for x in split_df_by_punct(df)]


def tokenize_text(wiki: WikiCode) -> List[List[Tuple[str, str]]]:
    text = " ".join(
        [s.strip() for s in str.splitlines(wiki.strip_code()) if len(s.strip()) > 0]
    )
    res = split_df_by_punct(pd.DataFrame(tokenize(text), columns=["word", "token"]))
    return res


@timing
def tag_sentences(sentence_list: List, tagged_titles_list: List):
    final = []
    for sent, tagged in zip(sentence_list, tagged_titles_list):
        grouped = list(split_when(tagged, split_BIO))
        found = {}
        last = -1
        for w in grouped:
            for i, word in enumerate(sent):
                if w[0][0] in word[0] and i > last:
                    if len(w) > 1:
                        for ii, z in enumerate(w):
                            found[i + ii] = z[1]
                    else:
                        found[i] = w[0][1]
                    last = i
                    break
        indexed = pd.DataFrame.from_dict(found, orient="index", columns=["tag"])
        final.append(
            pd.DataFrame(sent + [(".", "PUNCT")], columns=["word", "tokenized_as"])
            .join(indexed)
            .fillna("O")
        )
    return pd.concat(final)


def tag_page(page: str, tags: dict) -> pd.DataFrame:
    wiki = parse_wiki_page(page)
    tagged_titles_df = title_to_tag(wiki, tags)
    tagged_titles_list = tokenize_and_split_df(tagged_titles_df)
    sentence_list = tokenize_text(wiki)
    final_df = tag_sentences(sentence_list, tagged_titles_list)
    return final_df


def argparse_setup():
    parser = argparse.ArgumentParser()
    parser.add_argument("pages", nargs="*")
    parser.add_argument("--file", type=argparse.FileType("r"))
    parser.add_argument("--debug", type=str2bool, nargs="?", const=True, default=False)
    return parser.parse_args()


@timing
def main():
    args = argparse_setup()
    tags = basic_tag_prep()

    DEBUG = args.debug
    level = logging.DEBUG if DEBUG else logging.INFO
    logging.basicConfig(filename="log.log", level=level)

    tagged_pages = []
    if args.file:
        with args.file as f:
            for page in f.readlines():
                try:
                    tagged_pages.append(tag_page(page.rstrip(), tags))
                except Exception:
                    continue
    else:
        for page in args.pages:
            try:
                tagged_pages.append(tag_page(page, tags))
            except Exception:
                continue

    pd.concat(tagged_pages).to_csv("final.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()


## YAPPING
# df_list = []
# for i, sent in enumerate(text.split(". ")):
#     yapped = yap_it(sent + ".")
#     time.sleep(3)
#     df_list.append(pd_lattice(yapped["md_lattice"]))
#     if i > 10:
#         break
# word_and_pos = pd.concat(df_list)
