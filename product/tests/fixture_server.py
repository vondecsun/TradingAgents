"""Test-only server: provider fixtures never enter the production launcher."""
from datetime import date
from product.server.app import app
from product.server import market
from product.tests.test_product import chart_fixture


def fixture_history(symbol,start,end):
    if symbol == '600036.SH':
        raise market.MarketError('provider_timeout','测试网络超时：请点击重试')
    return market.parse_chart(chart_fixture(symbol),symbol,start,end)


market.fetch_daily=fixture_history
