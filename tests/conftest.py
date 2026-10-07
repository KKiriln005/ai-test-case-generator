import os

# app.main під час імпорту вимагає ключ (fail-fast). Реальний API в тестах не викликається.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
