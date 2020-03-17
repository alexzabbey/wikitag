import pandas as pd
from datetime import datetime
from collections import Counter
from functools import wraps
from more_itertools import split_after
import logging, argparse

## HELPERS
def most_popular(l):
    l = [x[1] for x in l]
    return Counter(l).most_common(1)[0][0]


def timing(f):
    @wraps(f)
    def wrap(*args, **kw):
        ts = datetime.now()
        result = f(*args, **kw)
        te = datetime.now()
        logging.debug(
            f"func: {f.__name__}, args: {[type(a) for a in args]}, took: {te-ts}"
        )
        return result

    return wrap


## DOMAIN-SPECIFIC HELPERS
def split_BIO(x, y):
    return (
        True
        if (x[1][0] == "B" and y[1][0] == "B") or (x[1][0] == "I" and y[1][0] == "B")
        else False
    )


def split_df_by_punct(df):
    l = list(
        split_after(df.to_records(index=False).tolist(), lambda x: x[0][-1] == ".")
    )
    fixed = []
    for sublist in l:
        if sublist[-1][0] == ".":
            fixed.append(sublist[:-1])
        else:
            sublist[-1] = (list(sublist[-1])[0][:-1], *sublist[-1][1:])
            fixed.append(sublist)
    return fixed


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")
