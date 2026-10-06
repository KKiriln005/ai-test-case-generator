"""Инкрементальный извлекатель тест-кейсов из потока частичного JSON (input_json_delta).

Структура ответа модели: { "summary": "...", "assumptions": [...], "test_cases": [ {...}, {...} ] }.
Глубина вложенности: корневой { = 1, массив [ = 2, объект тест-кейса { = 3. В кейсах нет вложенных
объектов, поэтому закрытие `}` на глубине 3 означает «кейс получен целиком».
Парсер учитывает строки и экранирование, так что скобки внутри текста кейсов ему не мешают.
"""
import json

_CASE_DEPTH = 3


class CaseExtractor:
    def __init__(self) -> None:
        self._buf = ""
        self._pos = 0
        self._depth = 0
        self._in_string = False
        self._escaped = False
        self._start: int | None = None

    def feed(self, chunk: str) -> list[dict]:
        """Принимает очередной кусок JSON, возвращает кейсы, завершившиеся в этом куске."""
        self._buf += chunk
        done: list[dict] = []
        while self._pos < len(self._buf):
            ch = self._buf[self._pos]
            if self._in_string:
                if self._escaped:
                    self._escaped = False
                elif ch == "\\":
                    self._escaped = True
                elif ch == '"':
                    self._in_string = False
            elif ch == '"':
                self._in_string = True
            elif ch in "{[":
                self._depth += 1
                if ch == "{" and self._depth == _CASE_DEPTH:
                    self._start = self._pos
            elif ch in "}]":
                if ch == "}" and self._depth == _CASE_DEPTH and self._start is not None:
                    done.append(json.loads(self._buf[self._start : self._pos + 1]))
                    self._start = None
                self._depth -= 1
            self._pos += 1
        return done
