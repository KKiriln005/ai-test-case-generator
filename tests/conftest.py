import os

# app.main при импорте требует ключ (fail-fast). Реальный API в тестах не вызывается.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
