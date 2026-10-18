"""One analysis per subprocess so timeouts/cancellation cannot leak tasks."""
import json
import sys
from decimal import Decimal


def run(data):
    from product.tls_setup import configure_tls
    configure_tls()
    if data['engine'] in ('tradingagents','backtest','settlement','model_check'):
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


def failure_details(exc):
    """Expose only fixed diagnostic text: never exception messages or provider bodies."""
    checks={
        'market_data_unavailable':'行情源预检失败：已在模型调用前停止；请检查数据源连接、限流或配置可用的A股数据接口',
        'model_check_tool_not_called':'模型自检未通过：模型没有执行要求的测试工具调用',
        'model_check_unexpected_tool':'模型自检未通过：模型请求了未提供的测试工具',
        'model_check_tool_not_finished':'模型自检未通过：工具返回后模型仍重复调用工具',
        'model_check_structured_missing':'模型自检未通过：未收到预期的结构化输出',
    }
    if isinstance(exc,ValueError) and str(exc) in checks:
        return {'code':str(exc),'message':checks[str(exc)]}
    chain=[]
    current=exc
    for _ in range(8):
        if current is None or any(current is item for item in chain):
            break
        chain.append(current)
        current=current.__cause__ or current.__context__
    statuses=[getattr(item,'status_code',None) for item in chain]
    names=' '.join(type(item).__name__.lower() for item in chain)
    errors={
        400:('provider_bad_request','外部服务拒绝请求参数（HTTP 400）：请核对模型ID、工具调用支持及参数配置'),
        401:('model_auth_failed','模型认证失败（HTTP 401）：请核对密钥及所选供应商'),
        402:('model_balance','模型服务拒绝请求（HTTP 402）：请检查余额或计费状态'),
        403:('provider_forbidden','外部服务拒绝访问（HTTP 403）：请检查模型或数据源权限'),
        404:('provider_not_found','外部服务资源不存在（HTTP 404）：请核对模型ID和服务端点'),
        429:('provider_rate_limit','外部服务限流或额度不足（HTTP 429）：请检查配额后再试'),
    }
    # Inspect only to select a fixed error category; never return provider bodies.
    bodies=' '.join(str(getattr(item,'body','')) for item in chain).lower()
    if 400 in statuses:
        hints=[
            ('reasoning_content','provider_reasoning_history','HTTP 400：供应商拒绝思考内容回传格式；请保留本任务，不要反复恢复'),
            ('tool_choice','provider_tool_choice','HTTP 400：供应商不接受当前tool_choice工具选择参数'),
            ('max_tokens','provider_token_limit','HTTP 400：max_tokens输出上限不符合该模型要求；请核对高级设置'),
            ('max_completion_tokens','provider_token_limit','HTTP 400：输出token参数不符合该模型要求'),
            ('content','provider_message_content','HTTP 400：供应商拒绝消息content内容格式'),
            ('model','provider_model_parameter','HTTP 400：供应商拒绝model参数；请核对所选端点及模型权限'),
            ('tools','provider_tools_schema','HTTP 400：供应商拒绝tools工具定义格式'),
        ]
        for word,code,message in hints:
            if word in bodies:return {'code':code,'message':message}
    for status in statuses:
        if status in errors:
            code,message=errors[status]
            return {'code':code,'message':message}
    if any(isinstance(item,(ImportError,ModuleNotFoundError)) for item in chain):
        code,message='dependency_missing','研究依赖导入失败：请使用原生研究启动文件重新安装依赖'
    elif 'unicode' in names:
        code,message='encoding_error','运行环境字符编码异常：请使用新版完整包及原生研究启动文件'
    elif 'timeout' in names:
        code,message='provider_timeout','外部模型或数据源响应超时：请检查网络后重试'
    elif any(term in names for term in ('connection','connecterror','proxyerror','sslerror')):
        code,message='provider_connection','无法连接外部模型或数据源：请检查网络、代理和证书'
    elif 'recursion' in names:
        code,message='graph_limit','原生分析达到图执行次数上限：请核对工具调用与轮数设置'
    else:
        code,message='engine_failed','引擎运行失败（'+type(exc).__name__[:60]+'）；原因尚未归类，需要进一步诊断'
    return {'code':code,'message':message}


if __name__ == '__main__':
    # Product IPC always uses UTF-8, including Windows consoles with a legacy code page.
    import contextlib
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    try:
        data = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            output = run(data)
        print(json.dumps(output, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'_engine_error':failure_details(exc)},ensure_ascii=False))
        sys.exit(1)
