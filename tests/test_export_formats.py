import csv
import io
import json

import pytest

from app.schemas import ExportFormat, TestCase, TestSuite
from app.services.export_service import export_suite


def make_suite(title: str = "Login is rejected") -> TestSuite:
    case = TestCase(
        id="TC-001", title=title, test_type="Negative", priority="Critical",
        preconditions="User exists", steps=["Open page", "Enter data", "Click Login"],
        expected_result="Error is shown", test_data="=SUM(1)",
    )
    return TestSuite(summary="s", assumptions=[], test_cases=[case])


def read_rows(fmt: ExportFormat) -> list[list[str]]:
    raw = export_suite(make_suite(), fmt).content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(raw)))


def test_zephyr_one_step_per_row():
    rows = read_rows(ExportFormat.ZEPHYR)
    assert len(rows) == 4  # заголовок + 3 шага
    first, middle, last = rows[1], rows[2], rows[3]
    assert first[0] == "Login is rejected"
    assert first[4] == "High"                 # Critical -> High
    assert first[6] == "'=SUM(1)"             # formula injection экранирован
    assert middle[0] == "" and middle[7] == ""
    assert last[7] == "Error is shown"        # ожидаемый результат - только на последнем шаге


def test_testrail_one_step_per_row():
    rows = read_rows(ExportFormat.TESTRAIL)
    assert len(rows) == 4
    assert rows[1][3] == "Critical"
    assert "Test data: =SUM(1)" in rows[1][5]
    assert rows[3][6] == "Error is shown"


def test_csv_standard_single_row_numbered_steps():
    rows = read_rows(ExportFormat.CSV)
    assert len(rows) == 2
    assert rows[1][5].splitlines()[0] == "1. Open page"


def test_json_roundtrip():
    result = export_suite(make_suite(), ExportFormat.JSON)
    assert result.extension == "json"
    assert json.loads(result.content)["test_cases"][0]["id"] == "TC-001"


def test_formula_injection_in_title_is_escaped():
    raw = export_suite(make_suite("=HYPERLINK(1)"), ExportFormat.CSV).content.decode("utf-8-sig")
    assert "'=HYPERLINK(1)" in raw


@pytest.mark.parametrize("fmt", list(ExportFormat))
def test_every_format_has_content(fmt):
    assert export_suite(make_suite(), fmt).content
