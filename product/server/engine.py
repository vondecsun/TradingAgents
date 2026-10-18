"""One analysis per subprocess so timeouts/cancellation cannot leak tasks."""
import json
import sys
from decimal import Decimal


def run(data):
    if data['engine'] in ('tradingagents','backtest','settlement'):
        from .native import run as run_native
        return run_native(data)
    bars = data['bars']
    if not bars:
        raise ValueError('没有可用历史数据')
    last = bars[-1]
    closes = [Decimal(b['close']) for b in bars]
    average = str((sum(closes[-5:]) / len(closes[-5:])).quantize(Decimal('0.0001')))
    report = {
        'title': data['symbol'] + ' 数据核对报告',
        'engine': data['engine'], 'as_of': data['as_of'],
        'mode': last['mode'], 'source': last['source'],
        'sections': [
            {'title': '可核查事实', 'text': f"数据截至 {last['date']}；收盘 {last['close']} 元；成交量 {last['volume']}；已提供 {len(bars)} 根日线。"},
            {'title': '计算指标', 'text': f'最近至多5条有效收盘记录均值 {average} 元。该指标不是买卖建议。'},
            {'title': '数据局限', 'text': '演示数据为合成；用户导入或在线历史日线未经交易所逐条核验。未接入公告、财务和实时行情；不推断其内容。历史模型可能存在知识泄漏。'},
        ],
        'evidence': [{'symbol': b['symbol'], 'date': b['date'], 'close': b['close'], 'source': b['source']} for b in bars[-20:]],
        'internal_only': data['engine'] == 'tradingagents',
    }
    return report


if __name__ == '__main__':
    # Upstream libraries may print; isolate final JSON from their stdout.
    import contextlib
    data = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        output = run(data)
    print(json.dumps(output, ensure_ascii=False))
