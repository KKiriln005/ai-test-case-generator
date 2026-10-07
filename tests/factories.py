"""Фабрики тестових даних."""


def make_case(n: int, **overrides) -> dict:
    data = {
        "id": f"WRONG-{n}",  # сервер зобов'язаний перенумерувати
        "title": f"Login scenario number {n}",
        "test_type": "Positive",
        "priority": "High",
        "preconditions": "None",
        "steps": ["Open the login page", "Submit the form"],
        "expected_result": "Success message is shown",
        "test_data": "N/A",
    }
    data.update(overrides)
    return data


def make_payload(count: int = 3) -> dict:
    """Відповідь моделі (input інструмента submit_test_suite)."""
    return {
        "summary": "Login feature.",
        "assumptions": ["Lockout policy is unknown"],
        "test_cases": [make_case(i) for i in range(1, count + 1)],
    }
