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
from more_itertools import split_when
from yap_tools import *
from apis import *
from helpers import *
from hebtokenizer import tokenize

### ACTIONS


@timing
def parse_wiki_page(page_title):
    wiki = mwp.parse(get_wp_fulltext(page_title))
    # remove files
    for l in wiki.filter_wikilinks():
        if l.startswith("[[קטגוריה") or l.startswith("[[קובץ"):
            wiki.remove(l)
    # remove extrenal links section
    wiki.remove(wiki.get_sections(matches=r"קישורים חיצוניים"))
    # remove headings
    for h in wiki.filter_headings():
        wiki.remove(h)
    # replace tags with text
    for x in wiki.filter_tags():
        index = wiki.index(x)
        wiki.remove(x)
        wiki.insert(index, x.contents)

    # further reading
    # photo gallery - https://he.wikipedia.org/wiki/%D7%AA%D7%A7%D7%95%D7%9E%D7%94/
    # tables - https://he.wikipedia.org/wiki/%D7%92%D7%9C%D7%A2%D7%93_%D7%A7%D7%9E%D7%97%D7%99
    print("finished parsing wiki page")
    return wiki


@timing
def tag_prep(filename="tags.yaml"):
    if os.path.isfile("prepped_tags.json"):
        with open("prepped_tags.json", "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        with open(filename, "r", encoding="utf-8") as f:
            tags = load(f, Loader=Loader)

        for k, v in tags.items():
            if type(v) == list:
                tags[k] = {"include": v, "exclude": None, "not": None}
            else:
                tags[k].setdefault("exclude", None)
                tags[k].setdefault("not", None)

        for k, v in tags.items():
            tags[k]["include"] = get_subclasses(v["include"], exclude=v["exclude"])
            tags[k]["not"] = get_subclasses(v["not"])
        print("finished prepping tags")
        for k, v in tags["ORG"].items():
            print(f"{k}: {type(v)}")
        with open("prepped_tags.json", "w", encoding="utf-8") as fp:
            json.dump(tags, fp)
        return tags


@timing
def title_to_tag(wiki, tags):
    # wp_title -> wdid -> instance -> tag
    # pair wdid with wp title
    Q_list = list(
        set(
            get_wdid_from_wp(str(t)) for t in [l.title for l in wiki.filter_wikilinks()]
        )
        - {False}
    )
    wdid_to_instance = instance_of(Q_list)
    title_to_instance = {}
    # for k, v in wp_title_to_wdid.items():
    #     if v != False:
    #         title_to_instance[k[0]] = wdid_to_instance[v]
    for k in [l.title for l in wiki.filter_wikilinks()]:
        v = get_wdid_from_wp(str(k))
        if v:
            title_to_instance[str(k)] = wdid_to_instance[v]

    tagged_titles = {}
    for title, Q_list in title_to_instance.items():
        options = []
        for Q in Q_list:
            for tag in tags:
                if Q in tags[tag]["not"]:
                    break
                if Q in tags[tag]["include"]:
                    options.append((Q, tag))
        tagged_titles[title] = options
    tagged_titles = {k: most_popular(v) for k, v in tagged_titles.items() if len(v) > 0}

    def tag_wikilink(wl):
        tagged_list = []
        tag = tagged_titles.get(str(wl.title), "O")
        text = str(wl.text).split() if wl.text else str(wl.title).split()
        tags = (
            [f"B-{tag}"] + [f"I-{tag}"] * len(text) if tag != "O" else [tag] * len(text)
        )
        return zip(text, tags)

    final = []
    for i, n in enumerate(wiki.nodes):
        if not isinstance(n, mwp.nodes.template.Template):
            if isinstance(n, mwp.nodes.text.Text):
                for x in n.split():
                    final.append((x, "O"))
            elif isinstance(n, mwp.nodes.wikilink.Wikilink):
                final += tag_wikilink(n)

    final_df = pd.DataFrame(final, columns=["untokenized_word", "tag"])

    def tokenize_df(df):
        df["untokenized_word"] = df["untokenized_word"].apply(tokenize)
        df = df.explode("untokenized_word")
        df[["word", "token"]] = pd.DataFrame(
            df["untokenized_word"].tolist(), index=df.index
        )
        return df[["word", "tag", "token"]].reset_index(drop=True)

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


if __name__ == "__main__":
    wiki = parse_wiki_page("רכבות במצרים")
    if not os.path.isfile("tagged_titles_list.pickle"):
        tags = tag_prep()
        tagged_titles_list = title_to_tag(wiki, tags)
        with open("tagged_titles_list.pickle", "wb") as f:
            pickle.dump(tagged_titles_list, f)
    else:
        with open("tagged_titles_list.pickle", "rb") as f:
            tagged_titles_list = pickle.load(f)
    sentence_list = tokenize_text(wiki)
    final_df = tag_sentences(sentence_list, tagged_titles_list)
    final_df.to_csv("final.csv", encoding="utf-8-sig")

## YAPPING
# df_list = []
# for i, sent in enumerate(text.split(". ")):
#     yapped = yap_it(sent + ".")
#     time.sleep(3)
#     df_list.append(pd_lattice(yapped["md_lattice"]))
#     if i > 10:
#         break
# word_and_pos = pd.concat(df_list)
