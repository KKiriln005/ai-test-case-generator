"""Pydantic-схеми: єдиний контракт між API, AI-сервісом та експортом.

Схема `TestSuite` водночас:
  1. валідує відповідь моделі,
  2. через `model_json_schema()` стає `input_schema` інструмента для Claude,
     тому `description` у полів - це інструкції для моделі.
"""
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TestType(str, Enum):
    __test__ = False  # щоб pytest не вважав клас тестовим
    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    BOUNDARY = "Boundary"          # Boundary Value Analysis
    EQUIVALENCE = "Equivalence"    # Equivalence Partitioning


class ExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"            # стандартний CSV: один кейс = один рядок
    ZEPHYR = "zephyr"      # Zephyr Scale CSV: один крок = один рядок
    TESTRAIL = "testrail"  # TestRail CSV (Test Case Steps): один крок = один рядок


class _Strict(BaseModel):
    # extra="forbid" -> additionalProperties: false в JSON Schema і відмова від «зайвих» полів.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TestCase(_Strict):
    __test__ = False

    id: str = Field(description="Sequential ID like TC-001. Will be re-numbered by the server.")
    title: str = Field(min_length=5, max_length=200, description="Short, specific title that states the checked behaviour.")
    test_type: TestType = Field(description="Positive, Negative, Boundary (BVA) or Equivalence (EP).")
    priority: Priority = Field(description="Business/risk based priority.")
    preconditions: str = Field(description="State required before the test. Use 'None' if there are no preconditions.")
    steps: list[str] = Field(min_length=1, max_length=20, description="Ordered, atomic, imperative actions. One action per item, without numbering.")
    expected_result: str = Field(min_length=3, description="Observable, verifiable outcome of the whole scenario.")
    test_data: str = Field(description="Concrete input values (e.g. 'password: Abcdef1!'). Use 'N/A' if no data is needed.")


class TestSuite(_Strict):
    __test__ = False

    summary: str = Field(description="2-3 sentence summary of what the requirements describe and which test design techniques were applied.")
    assumptions: list[str] = Field(default_factory=list, description="Ambiguities, gaps or assumptions found in the requirements. Empty list if none.")
    test_cases: list[TestCase] = Field(min_length=1, max_length=50)


# ---------- DTO для API ----------

class GenerateRequest(BaseModel):
    requirements: str = Field(min_length=20, max_length=10_000, description="User Story або вимоги")
    max_cases: int = Field(default=10, ge=3, le=30)
    language: Literal["uk", "en"] = "uk"

    @field_validator("requirements")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 20:
            raise ValueError("Вимоги занадто короткі: опишіть функціональність детальніше (від 20 символів).")
        return v


class ExportRequest(BaseModel):
    format: ExportFormat
    suite: TestSuite
