"""Public daily history adapter; no credentials, arbitrary URLs or real-time claims.

Uses Yahoo Finance's chart service (also used by upstream yfinance).
Personal research only; commercial redistribution is not implied.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CHINA = ZoneInfo('Asia/Shanghai')
SOURCE = 'Yahoo Finance · 历史日线报价 · 非实时'
MAX_BYTES = 2_000_000


class MarketError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalize_symbol(value):
    value = value.strip().upper()
    if re.fullmatch(r'60[0135]\d{3}|00[012]\d{3}', value):
        value += '.SH' if value.startswith('6') else '.SZ'
    if not re.fullmatch(r'(?:60[0135]\d{3}\.SH|00[012]\d{3}\.SZ)', value):
        raise ValueError('请输入沪深主板六位代码，例如000001或600519；本版暂不支持其他板块')
    return value


def date_range(start, end):
    latest = datetime.now(CHINA).date() - timedelta(days=1)
    if start > end or end > latest or (end-start).days > 5*366:
        raise ValueError('日期范围须在昨天及以前，开始不晚于结束，且最多5年')
    if start < date(1991, 1, 1):
        raise ValueError('开始日期不能早于1991年')


def parse_chart(payload, symbol, start, end):
    try:
        chart = payload['chart']
        if chart.get('error'):
            raise MarketError('provider_rejected', '数据源未能返回此证券，请检查代码或稍后重试')
        result = chart['result']
        if not result:
            raise MarketError('empty_data', '这个日期范围没有可用日线，请换一个范围')
        data = result[0]
        yahoo_symbol = symbol.replace('.SH', '.SS')
        if data['meta'].get('symbol', '').upper() != yahoo_symbol:
            raise MarketError('symbol_mismatch', '数据源返回了不同证券，已拒绝保存')
        if data['meta'].get('currency') not in ('CNY', 'CNH'):
            raise MarketError('currency_mismatch', '数据源币种不符合A股报价，已拒绝保存')
        timestamps = data.get('timestamp') or []
        if len(timestamps) > 2000:
            raise MarketError('too_many_rows', '数据源返回日线超出限制')
        if not timestamps:
            raise MarketError('empty_data', '这个日期范围没有可用日线，请换一个范围')
        quote = data['indicators']['quote'][0]
        if any(len(quote[k]) != len(timestamps) for k in ('open','high','low','close','volume')):
            raise MarketError('malformed_data', '行情字段长度不一致，未保存任何数据')
        records, seen, skipped = [], set(), 0
        for i, timestamp in enumerate(timestamps):
            day = datetime.fromtimestamp(timestamp, CHINA).date()
            if day < start or day > end:
                continue
            values = [quote[k][i] for k in ('open','high','low','close')]
            volume = quote['volume'][i]
            # Missing/suspended sessions are not invented as priced bars.
            if any(v is None for v in values) or volume is None:
                skipped += 1
                continue
            values = [Decimal(str(v)) for v in values]
            if any(not v.is_finite() or v <= 0 or v > 1_000_000 for v in values):
                raise MarketError('malformed_data', '日线含无效价格，未保存任何数据')
            values = [v.quantize(Decimal('.0001')) for v in values]
            o,h,l,c = values
            if l > min(o,c) or h < max(o,c) or day.weekday() >= 5:
                raise MarketError('malformed_data', '日线日期或OHLC关系异常，未保存任何数据')
            if type(volume) is not int or volume < 0 or volume > 10**15:
                raise MarketError('malformed_data', '成交量格式异常，未保存任何数据')
            if day in seen:
                raise MarketError('malformed_data', '数据源返回重复日期，未保存任何数据')
            seen.add(day)
            records.append({'symbol':symbol,'date':day.isoformat(),**dict(zip(('open','high','low','close'),[str(v) for v in values])),'volume':volume,'tradable':int(volume > 0),'source':SOURCE,'mode':'online'})
        if not records:
            raise MarketError('empty_data', '没有有效日线，可能尚未上市、已退市或所选日期均休市')
        return {'items':sorted(records,key=lambda x:x['date']),'source':SOURCE,'skipped':skipped,'provider':'yahoo','name':str(data['meta'].get('shortName') or symbol)[:150]}
    except MarketError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, InvalidOperation):
        raise MarketError('malformed_data', '数据源响应格式异常，未保存任何数据') from None


def fetch_daily(symbol, start, end):
    date_range(start, end)
    yahoo_symbol = symbol.replace('.SH', '.SS')
    params = {
        'period1':int(datetime.combine(start, time.min, CHINA).timestamp()),
        'period2':int(datetime.combine(end+timedelta(days=1), time.min, CHINA).timestamp()),
        'interval':'1d', 'events':'history',
    }
    # Only the fixed vendor host is used; symbols never become hostnames/URLs.
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + yahoo_symbol + '?' + urlencode(params)
    request = Request(url, headers={'User-Agent':'Hengyan/0.2 (personal research)','Accept':'application/json'})
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read(MAX_BYTES+1)
        if len(body) > MAX_BYTES:
            raise MarketError('response_too_large', '数据源响应过大，请缩短日期范围')
        return parse_chart(json.loads(body), symbol, start, end)
    except HTTPError as exc:
        if exc.code == 429:
            raise MarketError('provider_rate_limit', '数据源暂时限流，请稍后点击重试') from None
        if exc.code in (401,403):
            raise MarketError('provider_access_denied', '数据源暂时拒绝访问；请稍后重试或检查本机网络，系统没有用演示数据替代') from None
        raise MarketError('provider_unavailable', '行情服务暂时不可用，请稍后重试') from None
    except (TimeoutError, socket.timeout):
        raise MarketError('provider_timeout', '行情下载超时，请检查网络后重试') from None
    except (URLError, OSError):
        raise MarketError('provider_network', '无法连接行情服务，请检查网络后重试') from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise MarketError('malformed_data', '行情服务返回了非预期响应，请稍后重试') from None
