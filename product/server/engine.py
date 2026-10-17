"""One analysis per subprocess so timeouts/cancellation cannot leak tasks."""
import json
import sys
from decimal import Decimal


def run(data):
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
            {'title': '数据局限', 'text': '演示数据或用户导入数据未经行情供应商验证。未接入公告、财务和实时行情；不推断其内容。历史模型可能存在知识泄漏。'},
        ],
        'evidence': [{'symbol': b['symbol'], 'date': b['date'], 'close': b['close'], 'source': b['source']} for b in bars[-20:]],
        'internal_only': data['engine'] == 'tradingagents',
    }
    if data['engine'] == 'tradingagents':
        if last['mode'] == 'demo':
            raise ValueError('演示数据不能提交真实研究引擎')
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import build_default_config
        config = build_default_config()
        # No shared memories/checkpoints/reports between tenants or runs.
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory(prefix='ta-job-') as folder:
            config.update(results_dir=folder, data_cache_dir=str(Path(folder)/'cache'),
                          memory_log_path=str(Path(folder)/'memory.md'), output_language='简体中文')
            state, rating = TradingAgentsGraph(config=config).propagate(data['symbol'], data['as_of'])
            for key, title in [('market_report','技术研究'),('news_report','新闻研究'),('fundamentals_report','基本面研究'),('final_trade_decision','内部研究结论')]:
                if state.get(key):
                    report['sections'].append({'title': title, 'text': str(state[key])[:30000]})
            report['rating'] = rating
            report['sections'].append({'title': '内部研究范围', 'text': 'TradingAgents独立获取其配置数据源，不代表使用导入CSV重建完整历史信息；不得作为实盘委托。'})
    return report


if __name__ == '__main__':
    # Upstream libraries may print; isolate final JSON from their stdout.
    import contextlib
    data = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        output = run(data)
    print(json.dumps(output, ensure_ascii=False))
