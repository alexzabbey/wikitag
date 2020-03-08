from spacy import displacy
import requests
import pandas as pd

TOKEN = "75c969d3b38651e02e85b0e9fa175489"


def yap_it(text):
    text = text.replace(r'"', r"\"")
    url = f"https://www.langndata.com/api/heb_parser?token={TOKEN}"
    _json = '{"data":"' + text + '"}'
    headers = {"content-type": "application/json"}
    r = requests.post(
        url,
        data=_json.encode("utf-8"),
        headers={"Content-type": "application/json; charset=utf-8"},
    )
    r.raise_for_status()
    return r.json()


def fmt_dep_tree(dep_tree):
    return {
        "words": [{"text": v["word"], "tag": v["pos"]} for v in dep_tree.values()],
        "arcs": [
            {
                "start": int(v["num"]),
                "end": int(v["dependency_arc"]),
                "label": v["dependency_part"],
                "dir": "left",
            }
            for v in dep_tree.values()
        ],
    }


def tree_vis(fmted_dep_tree):
    displacy.render(fmted_dep_tree, style="dep", manual=True, page=False, minify=True)


def pd_lattice(lattice_dict):
    return pd.DataFrame.from_dict(lattice_dict).T.reset_index(drop=True)
