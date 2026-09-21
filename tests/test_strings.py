"""The English table must say everything the Persian one says, with the same blanks."""

import string

from podcast_workspace.ui import strings, strings_en


def _names(module: object) -> set[str]:
    return {name for name in vars(module) if name.isupper()}


def _fields(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_fields(v) for v in value.values())) if value else set()
    if not isinstance(value, str):
        return set()
    return {field for _, field, _, _ in string.Formatter().parse(value) if field}


def test_every_name_is_translated():
    assert _names(strings) == _names(strings_en)


def test_placeholders_match():
    mismatched = [
        name
        for name in _names(strings)
        if _fields(getattr(strings, name)) != _fields(getattr(strings_en, name))
    ]
    assert mismatched == []


def test_dict_keys_match():
    for name in _names(strings):
        fa, en = getattr(strings, name), getattr(strings_en, name)
        if isinstance(fa, dict):
            assert set(fa) == set(en), name
