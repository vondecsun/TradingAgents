"""Local operator setup: keys stay in process environment, never files or browser."""
import os
from pathlib import Path
import re
import runpy
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))


def main():
    from product.key_input import read_api_key
    from product.server.native import provider_registry
    registry=provider_registry()
    print('原生 TradingAgents 本地测试启动；不会自动调用收费模型。')
    email=(input('测试邮箱（回车使用 vondecsun@gmail.com）：').strip().lower() or 'vondecsun@gmail.com')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        raise ValueError('邮箱格式无效')
    print('可选供应商：'+', '.join(registry))
    provider=input('供应商ID（例如 deepseek / qwen-cn / openai / ollama）：').strip()
    if provider not in registry:
        raise ValueError('供应商未在原仓库注册')
    quick=input('输入该供应商实际支持的快速模型ID：').strip()
    deep=input('输入该供应商实际支持的深度模型ID（回车复用快速模型）：').strip() or quick
    if not quick:
        raise ValueError('模型ID不能为空')
    variable=registry[provider]
    if variable and provider!='openai_compatible':
        key=read_api_key('输入模型API密钥（不回显、不写入文件）：')
        if not key:
            raise ValueError('缺少密钥')
        os.environ[variable]=key
    if provider in ('openai_compatible','ollama'):
        endpoint=input('模型端点（ollama可留空，其他兼容服务必须填写）：').strip()
        if endpoint:
            parts=urlsplit(endpoint)
            if parts.username or parts.password or parts.scheme not in ('http','https') or not parts.hostname:
                raise ValueError('端点格式不安全，不能在URL中携带密码')
            if parts.scheme=='http' and parts.hostname not in ('localhost','127.0.0.1','::1'):
                raise ValueError('远程模型端点须使用HTTPS')
            os.environ['TRADINGAGENTS_LLM_BACKEND_URL']=endpoint
        elif provider=='openai_compatible':
            raise ValueError('兼容服务需要明确端点')
        if variable:
            key=read_api_key('端点密钥（本地无认证可留空）：',optional=True)
            if key:os.environ[variable]=key
    os.environ.update(PRODUCT_INTERNAL_RESEARCH='true',PRODUCT_INTERNAL_EMAILS=email,
                      TRADINGAGENTS_LLM_PROVIDER=provider,TRADINGAGENTS_QUICK_THINK_LLM=quick,
                      TRADINGAGENTS_DEEP_THINK_LLM=deep,PRODUCT_HOST='127.0.0.1')
    print('凭据仅在此窗口会话有效，关闭后需重新输入。')
    print('已有账户的研究设置若不同，请在“原生多代理研究”页保存所需配置。')
    runpy.run_path(str(ROOT/'product'/'launch.py'),run_name='__main__')


if __name__=='__main__':
    main()
