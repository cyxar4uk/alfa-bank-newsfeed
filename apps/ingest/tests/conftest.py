import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Тесты в сеть не ходят: дозаполнение картинок со страниц материалов получает пустой ответ."""
    monkeypatch.setattr("ingest.news.media.fetch_pages", lambda jobs, timeout=15.0: {})
    # и к моделям тоже: отсев сомнительных новостей без ключа пропускается
    monkeypatch.delenv("LLM_API_KEY", raising=False)
