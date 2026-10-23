import json
from pathlib import Path

from ingest import cli
from ingest.news.fetch import FeedReport, RawItem


def fake_fetch_ok(feeds, timeout=20.0):
    items = [
        RawItem(
            "cbr",
            "Банк России",
            0,
            "Банк России сохранил ключевую ставку 14%",
            "<p>Решение совета.</p>",
            "https://cbr.ru/press/1",
            "Fri, 23 Oct 2026 13:30:00 +0300",
        ),
    ]
    return items, [FeedReport("cbr", "Банк России", "https://cbr.ru/rss", ok=True, items=1)]


def fake_fetch_down(feeds, timeout=20.0):
    return [], [FeedReport("cbr", "Банк России", "https://cbr.ru/rss", ok=False, error="нет сети")]


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_news_command_writes_output_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.news.pipeline.fetch_all", fake_fetch_ok)
    assert cli.main(["news", "--data", str(tmp_path), "--snapshot"]) == 0

    out = lines(tmp_path / "raw" / "derived" / "news.jsonl")
    snap = lines(tmp_path / "demo" / "news_snapshot.jsonl")
    assert out == snap
    assert out[0]["kind"] == "news" and out[0]["fragment"] == "Решение совета."
    assert set(out[0]) <= {
        "id",
        "kind",
        "title",
        "publisher",
        "url",
        "published_at",
        "fragment",
        "tags",
        "also_reported_by",
    }
    report = json.loads((tmp_path / "raw" / "derived" / "report.json").read_text("utf-8"))
    assert report["news"]["news"] == 1


def test_news_falls_back_to_snapshot_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.news.pipeline.fetch_all", fake_fetch_ok)
    cli.main(["news", "--data", str(tmp_path), "--snapshot"])
    monkeypatch.setattr("ingest.news.pipeline.fetch_all", fake_fetch_down)
    cli.main(["news", "--data", str(tmp_path), "--snapshot"])

    assert len(lines(tmp_path / "raw" / "derived" / "news.jsonl")) == 1
    assert len(lines(tmp_path / "demo" / "news_snapshot.jsonl")) == 1
    report = json.loads((tmp_path / "raw" / "derived" / "report.json").read_text("utf-8"))
    assert report["news"]["from_snapshot"] is True


def test_analytics_without_pdfs_is_skipped_not_failed(tmp_path):
    assert cli.main(["analytics", "--data", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "raw" / "derived" / "report.json").read_text("utf-8"))
    assert "skipped" in report["analytics"]
