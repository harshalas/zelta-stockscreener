from datetime import datetime, timezone

import vector_pipeline


class _FakeCursor:
    def __init__(self):
        self.executed: list[tuple] = []

    def execute(self, sql, params):
        self.executed.append(params)

    def close(self):
        pass


class _FakeDB:
    def __init__(self):
        self.cursor_obj = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_parse_published_at_converts_finnhub_unix_timestamp():
    article = {"datetime": 1700000000}
    assert vector_pipeline._parse_published_at(article) == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )


def test_parse_published_at_prefers_an_explicit_datetime_over_finnhub_field():
    explicit = datetime(2024, 1, 1, tzinfo=timezone.utc)
    article = {"published_at": explicit, "datetime": 1700000000}
    assert vector_pipeline._parse_published_at(article) == explicit


def test_parse_published_at_returns_none_when_neither_field_present():
    assert vector_pipeline._parse_published_at({}) is None


def test_parse_published_at_returns_none_for_garbage_values():
    assert vector_pipeline._parse_published_at({"datetime": "not-a-timestamp"}) is None


def test_process_ticker_stamps_ticker_onto_raw_finnhub_articles(monkeypatch):
    """Regression test for the production bug: real Finnhub company-news
    articles never carry a "ticker" key (only the query symbol does), so
    store_article crashed with KeyError('ticker') on every real harvest --
    analysis jobs silently fell back to technical-only sentiment as a
    result. process_ticker must inject the ticker itself."""
    fake_db = _FakeDB()
    monkeypatch.setattr(vector_pipeline, "get_db", lambda: fake_db)
    monkeypatch.setattr(vector_pipeline, "embed_text", lambda text: [0.1, 0.2])

    articles = [
        {
            "headline": "Company beats earnings",
            "summary": "Great quarter.",
            "datetime": 1700000000,
        }
    ]

    vector_pipeline.process_ticker("AAPL", articles)

    assert fake_db.committed
    assert not fake_db.rolled_back
    inserted_ticker = fake_db.cursor_obj.executed[0][0]
    assert inserted_ticker == "AAPL"


def test_process_ticker_keeps_an_explicit_ticker_if_already_present(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(vector_pipeline, "get_db", lambda: fake_db)
    monkeypatch.setattr(vector_pipeline, "embed_text", lambda text: [0.1, 0.2])

    articles = [{"ticker": "MSFT", "headline": "Other ticker mentioned", "datetime": 1700000000}]

    vector_pipeline.process_ticker("AAPL", articles)

    inserted_ticker = fake_db.cursor_obj.executed[0][0]
    assert inserted_ticker == "MSFT"


def test_store_article_writes_the_parsed_published_at(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(vector_pipeline, "embed_text", lambda text: [0.1, 0.2])

    article = {"ticker": "AAPL", "headline": "Headline", "datetime": 1700000000}
    vector_pipeline.store_article(article, fake_db)

    inserted_published_at = fake_db.cursor_obj.executed[0][4]
    assert inserted_published_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
