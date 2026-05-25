"""
tests/test_scrapers.py
Basic smoke tests for all scrapers.
Run with: pytest tests/ -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPriceData:
    def test_get_stock_info_valid_ticker(self):
        from scrapers.price_data import get_stock_info
        info = get_stock_info("MARA")
        assert info is not None
        assert "price" in info
        assert "ticker" in info
        assert info["ticker"] == "MARA"

    def test_get_stock_info_invalid_ticker(self):
        from scrapers.price_data import get_stock_info
        info = get_stock_info("XYZXYZXYZ")
        assert info is None

    def test_calculate_momentum(self):
        from scrapers.price_data import calculate_momentum
        score = calculate_momentum("MARA")
        assert 0.0 <= score <= 1.0

    def test_score_short_squeeze(self):
        from scrapers.price_data import score_short_squeeze
        score = score_short_squeeze("MARA")
        assert 0.0 <= score <= 1.0

    def test_meets_screen_criteria(self):
        from scrapers.price_data import meets_screen_criteria
        # Stock clearly above our price range
        fake_info = {"price": 1500, "market_cap": 3_000_000_000_000, "avg_volume": 1_000_000, "float_shares": 15_000_000_000}
        assert meets_screen_criteria(fake_info) is False


class TestFinvizScreen:
    def test_fallback_universe(self):
        from scrapers.finviz_screen import get_fallback_universe
        universe = get_fallback_universe()
        assert len(universe) > 0
        assert all(isinstance(t, str) for t in universe)


class TestCatalystScraper:
    def test_earnings_date_returns_none_or_dict(self):
        from scrapers.catalyst_scraper import get_earnings_date
        result = get_earnings_date("MARA")
        assert result is None or isinstance(result, dict)

    def test_score_catalyst_no_catalyst(self):
        from scrapers.catalyst_scraper import score_catalyst_signal
        import pandas as pd
        score = score_catalyst_signal("XYZXYZ", pd.DataFrame())
        assert score == 0.0


class TestNewsScraper:
    def test_format_headlines_empty(self):
        from scrapers.news_scraper import format_headlines_for_ai
        result = format_headlines_for_ai("MARA", [])
        assert "No recent news" in result

    def test_format_headlines_with_data(self):
        from scrapers.news_scraper import format_headlines_for_ai
        articles = [{"title": "MARA Reports Strong Q1", "source": "Reuters", "description": "Details here"}]
        result = format_headlines_for_ai("MARA", articles)
        assert "MARA" in result
        assert "Reuters" in result


class TestScoringEngine:
    def test_stock_score_total(self):
        from scoring.engine import StockScore
        stock = StockScore(
            ticker="TEST",
            price=10.0,
            insider_score=0.8,
            reddit_score=0.6,
            options_score=0.5,
            catalyst_score=0.7,
            squeeze_score=0.4,
        )
        assert 0 <= stock.total_score <= 100

    def test_position_size(self):
        from scoring.engine import StockScore
        stock = StockScore(ticker="TEST", price=10.0)
        stock.insider_score = 1.0
        stock.reddit_score = 1.0
        stock.options_score = 1.0
        stock.catalyst_score = 1.0
        stock.squeeze_score = 1.0
        assert stock.position_size(100) == 40.0  # 40% of $100 budget

    def test_stop_loss_below_price(self):
        from scoring.engine import StockScore
        stock = StockScore(ticker="TEST", price=12.0)
        assert stock.stop_loss_price() < 12.0

    def test_price_target_above_price(self):
        from scoring.engine import StockScore
        stock = StockScore(ticker="TEST", price=12.0)
        assert stock.price_target() > 12.0
