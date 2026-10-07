"""Інкрементальний екстрактор тест-кейсів з потоку часткового JSON (input_json_delta).

Структура відповіді моделі: { "summary": "...", "assumptions": [...], "test_cases": [ {...}, {...} ] }.
Глибина вкладеності: кореневий { = 1, масив [ = 2, об'єкт тест-кейса { = 3. У кейсах немає вкладених
об'єктів, тому закриття `}` на глибині 3 означає «кейс отримано повністю».
Парсер враховує рядки та екранування, тож дужки всередині тексту кейсів йому не заважають.
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
        """Приймає черговий шматок JSON, повертає кейси, що завершилися в цьому шматку."""
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
