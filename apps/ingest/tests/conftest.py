import pytest


@pytest.fixture(autouse=True)
def no_page_fetch(monkeypatch):
    """Тесты в сеть не ходят: дозаполнение картинок со страниц материалов получает пустой ответ."""
    monkeypatch.setattr("ingest.news.media.fetch_pages", lambda jobs, timeout=15.0: {})
