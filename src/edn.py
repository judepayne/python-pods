import edn_format


def transform_dict(d):
    print(d)
    if isinstance(d, edn_format.immutable_dict.ImmutableDict):
        return {k: transform_dict(v) for k, v in d.items()}
    elif isinstance(d, (list, edn_format.immutable_list.ImmutableList)):
        return [transform_dict(item) for item in d]
    elif isinstance(d, edn_format.edn_lex.Symbol):
        return d.name
    elif isinstance(d, edn_format.edn_lex.Keyword):
        return d.name
    else:
        return d


def from_edn(s):
    res = transform_dict(edn_format.loads(s))
    return res


def to_edn(d):
    return edn_format.dumps(d)