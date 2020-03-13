# ### Idea
# 1. word2vec => vector for each word
# 2. phrase detection (https://radimrehurek.com/gensim/models/phrases.html)
# 3. (retrain?)
# 4. tag words with NER tags
# 5. simple classification model
#
# ### Other ideas
# 1. create NER tagged wikipedia text by links to pages with wikidata pages (!)
# 2. TFIDF(? or such) to find interesting/important terms
# 3. https://towardsdatascience.com/wikipedia-data-science-working-with-the-worlds-largest-encyclopedia-c08efbac5f5c


# improve caching and/or store things in db
import re, os, pickle, json
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

### ACTIONS

WikiCode = mwp.wikicode.Wikicode
WikiLink = mwp.nodes.wikilink.Wikilink


@timing
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
    for l in wiki.get_lists():
        del l[:]
    for x in ["templates", "tables"]:
        for attr in getattr(wiki, x):
            del attr[:]
    # replace tags with text
    for tag in wiki.get_tags():
        print(tag)

    # for x in wiki.filter_tags():
    #     index = wiki.index(x)
    #     wiki.remove(x)
    #     wiki.insert(index, x.contents)

    # further reading
    # photo gallery - https://he.wikipedia.org/wiki/%D7%AA%D7%A7%D7%95%D7%9E%D7%94/
    print("finished parsing wiki page")
    return mwp.parse(wiki.string)


def basic_tag_prep():
    with open("tags.yaml", "r", encoding="utf-8") as f:
        tags = load(f, Loader=Loader)
    for k, v in tags.items():
        if type(v) == list:
            tags[k] = {"include": v, "exclude": None, "not": None}
        else:
            tags[k].setdefault("exclude", None)
            tags[k].setdefault("not", None)
    return tags


# @timing
# def tag_prep(filename: str = "tags.yaml") -> dict:  # FIX: upgrade typing
#     if os.path.isfile("prepped_tags.json"):
#         with open("prepped_tags.json", "r", encoding="utf-8") as f:
#             return json.load(f)
#     else:
#         with open(filename, "r", encoding="utf-8") as f:
#             tags = load(f, Loader=Loader)

#         for k, v in tags.items():
#             if type(v) == list:
#                 tags[k] = {"include": v, "exclude": None, "not": None}
#             else:
#                 tags[k].setdefault("exclude", None)
#                 tags[k].setdefault("not", None)

#         for k, v in tags.items():
#             tags[k]["include"] = get_subclasses(v["include"], exclude=v["exclude"])
#             tags[k]["not"] = get_subclasses(v["not"])
#         print("finished prepping tags")
#         with open("prepped_tags.json", "w", encoding="utf-8") as fp:
#             json.dump(tags, fp)
#         return tags


def create_query(chunk: List[str], tags: dict, debug: bool = False):
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


@timing
def title_to_tag(wiki: WikiCode, tags: dict, debug: bool = False):
    # # wp_title -> wdid -> instance -> tag
    results = []
    titles = [str(l.title).replace('"', '\\"') for l in wiki.filter_wikilinks()]
    # ?i = item, ?ti = title, ?cl = class, ?t = tag ?sc = superclass, ?sl = sitelink
    try:
        for chunk in list(chunked(titles, 20)):
            results += sparql_query(create_query(chunk, tags, debug))
    except exceptions.HTTPError:
        results = []
        for chunk in list(chunked(titles, 10)):
            results += sparql_query(create_query(chunk, tags, debug))
    if debug:
        pd.DataFrame(results).to_csv(
            "wikidata_query_results.csv", index=False, encoding="utf-8-sig"
        )
    tagged_titles = {}
    for k, g in groupby(results, key=lambda x: x["ti"]):
        tagged_titles[k] = max(
            {x["t"]: x["c"] for x in list(g)}.items(), key=itemgetter(1)
        )[0]
    print(tagged_titles)

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
    final_df.to_csv("test.csv", encoding="utf-8-sig")

    def tokenize_df(df):
        df["untokenized_word"] = df["untokenized_word"].apply(tokenize)
        df = df.explode("untokenized_word")
        df[["word", "token"]] = pd.DataFrame(
            df["untokenized_word"].tolist(), index=df.index
        )
        return df[["word", "tag", "token"]].reset_index(drop=True)

    # tokenize_df(final_df).to_csv("test.csv", encoding="utf-8-sig")
    return [
        [y for y in x if y[1] != "O"] for x in split_df_by_punct(tokenize_df(final_df))
    ]


def tokenize_text(wiki):
    text = " ".join(
        [s.strip() for s in str.splitlines(wiki.strip_code()) if len(s.strip()) > 0]
    )
    return split_df_by_punct(pd.DataFrame(tokenize(text), columns=["word", "token"]))


@timing
def tag_sentences(sentence_list, tagged_titles_list):
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


@timing
def main():
    wiki = parse_wiki_page("רכבות במצרים")
    # if not os.path.isfile("tagged_titles_list.pickle"):
    # tags = tag_prep()
    tags = basic_tag_prep()
    tagged_titles_list = title_to_tag(wiki, tags, debug=False)
    # with open("tagged_titles_list.pickle", "wb") as f:
    #     pickle.dump(tagged_titles_list, f)
    # else:
    # with open("tagged_titles_list.pickle", "rb") as f:
    #     tagged_titles_list = pickle.load(f)
    sentence_list = tokenize_text(wiki)
    final_df = tag_sentences(sentence_list, tagged_titles_list)
    final_df.to_csv("final.csv", encoding="utf-8-sig")


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

## OLD
# def title_to_tag(wiki: WikiCode, tags: dict):
# # wp_title -> wdid -> instance -> tag
# # pair wdid with wp title
# {str(t): get_wdid_from_wp(str(t)) for t in [l.title for l in wiki.filter_wikilinks()]}

# Q_list = list(
#     set(
#         get_wdid_from_wp(str(t)) for t in [l.title for l in wiki.filter_wikilinks()]
#     )
#     - {False}
# )
# wdid_to_instance = get_instance_of(Q_list)

# pprint(Q_list)
# pprint(wdid_to_instance)

# title_to_instance = {}
# # for k, v in wp_title_to_wdid.items():
# #     if v != False:
# #         title_to_instance[k[0]] = wdid_to_instance[v]
# for k in [l.title for l in wiki.filter_wikilinks()]:
#     if v:
#         title_to_instance[str(k)] = wdid_to_instance[v]

