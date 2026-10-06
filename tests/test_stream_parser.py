import json

import pytest

from app.services.stream_parser import CaseExtractor
from tests.factories import make_case, make_payload


@pytest.mark.parametrize("size", [1, 3, 7, 50])
def test_extracts_all_cases_for_any_chunk_size(size):
    payload = make_payload(3)
    text = json.dumps(payload)
    extractor, got = CaseExtractor(), []

    for i in range(0, len(text), size):
        got += extractor.feed(text[i : i + size])

    assert got == payload["test_cases"]


def test_brackets_and_quotes_inside_strings_do_not_break_parsing():
    tricky = make_case(1, title='Braces {x} ] "quoted" \\ backslash', steps=["Type '}' and \"]\""])
    payload = {"summary": "s {", "assumptions": ["a ["], "test_cases": [tricky]}
    extractor, got = CaseExtractor(), []

    for ch in json.dumps(payload):
        got += extractor.feed(ch)

    assert got == [tricky]


def test_case_is_emitted_only_when_complete():
    text = json.dumps(make_payload(1))
    extractor = CaseExtractor()

    assert extractor.feed(text[:-20]) == []
    assert len(extractor.feed(text[-20:])) == 1
