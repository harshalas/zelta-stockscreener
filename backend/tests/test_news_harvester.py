import news_harvester


def test_harvest_caps_articles_to_the_most_recent_n(monkeypatch):
    """Regression test: a heavily-covered ticker (e.g. AAPL) can return
    200+ articles from Finnhub for a 7-day window. Embedding every one of
    them sequentially routinely took over a minute on the very first
    analysis of that ticker, blowing past the frontend's polling timeout.
    Only the most recent N should ever reach process_ticker."""
    articles = [
        {"headline": f"headline {i}", "datetime": i}
        for i in range(50)
    ]
    monkeypatch.setattr(news_harvester, "fetch_news", lambda ticker: articles)

    processed_batches = []

    def fake_process_ticker(ticker, batch):
        processed_batches.append(batch)

    monkeypatch.setitem(
        __import__("sys").modules,
        "vector_pipeline",
        type("_M", (), {"process_ticker": staticmethod(fake_process_ticker)})(),
    )

    result = news_harvester.harvest_and_pipeline_news("AAPL", max_articles=10)

    assert len(processed_batches) == 1
    batch = processed_batches[0]
    assert len(batch) == 10
    # Newest first: datetime=49 down to datetime=40.
    assert [article["datetime"] for article in batch] == list(range(49, 39, -1))
    assert result["articles_processed"] == 10


def test_harvest_defaults_to_the_module_level_cap(monkeypatch):
    articles = [{"headline": f"headline {i}", "datetime": i} for i in range(100)]
    monkeypatch.setattr(news_harvester, "fetch_news", lambda ticker: articles)

    processed_batches = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "vector_pipeline",
        type(
            "_M",
            (),
            {"process_ticker": staticmethod(lambda ticker, batch: processed_batches.append(batch))},
        )(),
    )

    news_harvester.harvest_and_pipeline_news("AAPL")

    assert len(processed_batches[0]) == news_harvester.MAX_ARTICLES_PER_HARVEST


def test_harvest_returns_early_when_no_articles_found(monkeypatch):
    monkeypatch.setattr(news_harvester, "fetch_news", lambda ticker: [])
    result = news_harvester.harvest_and_pipeline_news("AAPL")
    assert result == {"status": "no articles found", "ticker": "AAPL"}
