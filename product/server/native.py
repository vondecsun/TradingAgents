"""Thin integration around the ORIGINAL TradingAgents APIs, never replacement agents."""
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import threading
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db, market

ROOT=Path(__file__).resolve().parents[2]
ANALYSTS=['market','social','news','fundamentals']
NATIVE_ENGINES=('tradingagents','backtest','settlement')
# The provider mapping comes from the upstream light-weight registry.

def upstream_defaults():
    from tradingagents.default_config import build_default_config
    return build_default_config()


def provider_registry():
    from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
    return PROVIDER_API_KEY_ENV


class ResearchSettings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    llm_provider: str='openai'
    quick_think_provider: str | None=None
    deep_think_provider: str | None=None
    quick_think_llm: str=Field(default='gpt-6-luna',min_length=1,max_length=120)
    deep_think_llm: str=Field(default='gpt-6-sol',min_length=1,max_length=120)
    analysts: list[Literal['market','social','news','fundamentals']]=Field(default_factory=lambda:list(ANALYSTS),min_length=1,max_length=4)
    max_debate_rounds: int=Field(default=1,ge=1,le=5)
    max_risk_discuss_rounds: int=Field(default=1,ge=1,le=5)
    max_tool_rounds: int=Field(default=20,ge=1,le=20)
    max_recur_limit: int=Field(default=100,ge=100,le=1000)
    checkpoint_enabled: bool=True
    holding_period_days: int=Field(default=5,ge=1,le=60)
    output_language: str=Field(default='简体中文',min_length=1,max_length=40)
    max_tokens: int | None=Field(default=None,ge=256,le=32768)
    temperature: float | None=Field(default=None,ge=0,le=2,allow_inf_nan=False)
    llm_max_retries: int=Field(default=2,ge=0,le=5)
    openai_reasoning_effort: str | None=Field(default=None,max_length=30)
    anthropic_effort: str | None=Field(default=None,max_length=30)
    google_thinking_level: str | None=Field(default=None,max_length=30)
    data_vendors: dict[str,str]=Field(default_factory=dict,max_length=10)
    tool_vendors: dict[str,str]=Field(default_factory=dict,max_length=30)

    @field_validator('llm_provider','quick_think_provider','deep_think_provider')
    @classmethod
    def providers(cls,value):
        if value is not None and value not in provider_registry():
            raise ValueError('供应商不在原仓库注册表中')
        return value

    @field_validator('quick_think_llm','deep_think_llm')
    @classmethod
    def models(cls,value):
        if not re.fullmatch(r'[A-Za-z0-9_./:@+\-]+',value):
            raise ValueError('模型ID格式无效')
        return value

    @field_validator('analysts')
    @classmethod
    def unique(cls,value):
        if len(set(value))!=len(value):
            raise ValueError('分析师不能重复')
        return value

    @field_validator('data_vendors','tool_vendors')
    @classmethod
    def vendors(cls,value):
        # Only registry names, never custom addresses from an untrusted browser.
        for key,chain in value.items():
            if not re.fullmatch(r'[a-z_]{1,60}',key) or not re.fullmatch(r'[a-z_]+(?:,[a-z_]+)*',chain):
                raise ValueError('数据商配置必须为注册表名称')
        return value


def defaults():
    source=upstream_defaults()
    values={k:v for k,v in source.items() if k in ResearchSettings.model_fields}
    values.update(checkpoint_enabled=True,output_language='简体中文',llm_max_retries=source.get('llm_max_retries') if source.get('llm_max_retries') is not None else 2)
    return ResearchSettings(**values).model_dump()


def load_settings(con,uid):
    row=con.execute('SELECT config FROM research_settings WHERE user_id=?',(uid,)).fetchone()
    return ResearchSettings(**json.loads(row['config'])).model_dump() if row else defaults()


def tenant_root(uid):
    if not re.fullmatch(r'[a-f0-9]{32}',uid):
        raise ValueError('无效用户标识')
    base=Path(os.getenv('PRODUCT_RESEARCH_DIR') or str(Path(os.getenv('PRODUCT_DB','product-data/product.sqlite3')).resolve().parent/'research')).resolve()
    return base/'users'/uid


def job_root(uid,jid):
    if not re.fullmatch(r'[a-f0-9]{32}',jid):
        raise ValueError('无效任务标识')
    return tenant_root(uid)/'jobs'/jid


def build_config(settings,uid,jid):
    config=copy.deepcopy(upstream_defaults())
    config.update({k:v for k,v in settings.items() if k not in ('analysts','data_vendors','tool_vendors')})
    config['data_vendors'].update(settings.get('data_vendors',{}))
    config['tool_vendors'].update(settings.get('tool_vendors',{}))
    private=tenant_root(uid)
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name!='nt':private.chmod(0o700)
    root=job_root(uid,jid)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    config.update(results_dir=str(root/'results'),data_cache_dir=str(root/'checkpoints'),memory_log_path=str(tenant_root(uid)/'memory'/'trading_memory.md'))
    # Endpoints may ONLY be set in the trusted server environment / upstream config.
    return config


def capability(settings):
    missing=[]
    for distribution in ('langgraph','langchain-core','langchain-openai','langchain-anthropic','langchain-google-genai','langgraph-checkpoint-sqlite','pandas','yfinance','stockstats'):
        try:importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:missing.append(distribution)
    credentials=[]
    registry=provider_registry()
    for tier in ('quick','deep'):
        provider=settings.get(tier+'_think_provider') or settings['llm_provider']
        env=registry[provider]
        optional=provider in ('ollama','openai_compatible','bedrock')
        credentials.append({'tier':tier,'provider':provider,'model':settings[tier+'_think_llm'],'env_name':env,'configured':optional or bool(os.getenv(env or '')),'verified':False})
    return {'dependencies_ready':not missing,'missing_dependencies':missing,'tiers':credentials,'configured':not missing and all(x['configured'] for x in credentials),'live_verified':False,'note':'配置检测不是模型连接或分析质量验证；不会自动发起付费调用'}


def require_ready(settings):
    cap=capability(settings)
    if not cap['dependencies_ready']:
        raise ValueError('原生研究依赖尚未安装，请运行 product/setup-research-windows.bat')
    if not all(t['configured'] for t in cap['tiers']):
        raise ValueError('原生研究模型凭据未配置，请在服务器环境配置所选供应商密钥；不会切换到简化分析')


def integrity():
    manifest=json.loads((ROOT/'product'/'UPSTREAM_CORE_MANIFEST.json').read_text(encoding='utf-8'))
    mismatches=[]
    for item in manifest['files']:
        p=ROOT/item['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            mismatches.append(item['path'])
    return {'repository':manifest['repository'],'upstream_version':manifest['upstream_version'],'source_commit':manifest['source_commit'],'checked_files':len(manifest['files']),'unchanged':not mismatches,'mismatches':mismatches}


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,default=str),encoding='utf-8')
    temp.replace(path)


def progress_path(uid,jid):
    return job_root(uid,jid)/'progress.json'


def stages_callback(uid,jid):
    from langchain_core.callbacks import BaseCallbackHandler
    class Progress(BaseCallbackHandler):
        def __init__(self):
            self.calls=0
            self.lock=threading.Lock()
        def on_chat_model_start(self,*args,**kwargs):
            with self.lock:
                self.calls+=1
                atomic_json(progress_path(uid,jid),{'stage':f'原生代理正在调用模型（第{self.calls}次）','model_calls':self.calls})
    return Progress()


def portfolio_context(value):
    if value is None:
        return None
    from tradingagents.portfolio import PortfolioContext
    data=copy.deepcopy(value)
    for position in data.get('positions',[]):
        position['ticker']=market.normalize_symbol(position['ticker']).replace('.SH','.SS')
    return PortfolioContext.model_validate(data)


def _base(data,title):
    return {'title':title,'engine':data['engine'],'as_of':data.get('as_of'),'mode':'upstream','source':'原仓库 TradingAgentsGraph 与其数据源','sections':[],'evidence':[],'internal_only':True,'native':True}


def run(data):
    """Invoke upstream analysis/backtest/settlement without rewriting any agent."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.reporting import _SECTIONS
    uid,jid=data['_user_id'],data['_job_id']
    folder=job_root(uid,jid)
    output=folder/'result.json'
    if output.is_file():
        return json.loads(output.read_text(encoding='utf-8'))
    settings=ResearchSettings(**data['research_settings']).model_dump()
    config=build_config(settings,uid,jid)
    portfolio=portfolio_context(data.get('portfolio'))
    callbacks=[stages_callback(uid,jid)]
    atomic_json(progress_path(uid,jid),{'stage':'正在构建原仓库代理图','model_calls':0})
    if data['engine']=='backtest':
        from dataclasses import asdict
        from tradingagents.backtest import run_backtest,summarize
        tickers=[market.normalize_symbol(x).replace('.SH','.SS') for x in data['tickers']]
        def progress(done,total,ticker,day):
            atomic_json(progress_path(uid,jid),{'stage':f'原生回测 {done}/{total} · {ticker} · {day}','done':done,'total':total})
        result=run_backtest(tickers,data['dates'],config,portfolio=portfolio,selected_analysts=settings['analysts'],run_id=jid,progress=progress)
        if result.cells_run+result.skipped==0:
            raise RuntimeError('native_backtest_no_completed_cells')
        summary=summarize(result)
        report=_base(data,'TradingAgents 原生评级回测')
        report['sections']=[{'title':'原生回测评分','text':summary.render()},{'title':'解释','text':'这是原仓库的评级质量评估，不是资金组合成交回测；模型采样及历史信息可见性限制仍然存在。'}]
        report['backtest']={'summary':asdict(summary),'run_id':result.run_id,'cells_run':result.cells_run,'skipped':result.skipped,'failures':[(x[0],x[1],'upstream_cell_failed') for x in result.failures],'settlement_failures':len(result.settlement_failures)}
    else:
        graph=TradingAgentsGraph(selected_analysts=settings['analysts'],config=config,callbacks=callbacks)
        if data['engine']=='settlement':
            settled=graph.settle_all_pending()
            entries=graph.memory_log.load_entries()
            report=_base(data,'TradingAgents 历史决策结算与反思')
            report['sections']=[{'title':'结算结果','text':f'本次结算 {len(settled.settled)} 条，失败 {len(settled.failed)} 条；持有窗口尚未结束的决策继续待结算。'}]
            report['settlement']={'settled':settled.settled,'failed':[(x[0],x[1],'upstream_settlement_failed') for x in settled.failed],'entries':entries}
        else:
            ticker=market.normalize_symbol(data['symbol']).replace('.SH','.SS')
            state,rating=graph.propagate(ticker,data['as_of'],portfolio=portfolio)
            graph.save_reports(state,ticker,save_path=folder/'reports',html=True)
            report=_base(data,data['symbol']+' · TradingAgents 完整原生分析')
            report['rating']=rating
            report['settings']=graph.run_settings()
            coverage=[]
            for heading,_directory,agents in _SECTIONS:
                for agent,_filename,path in agents:
                    value=state
                    for key in path:
                        value=(value or {}).get(key)
                    coverage.append({'agent':agent,'available':bool(value),'state_path':'.'.join(path)})
                    if value:
                        report['sections'].append({'title':agent,'text':str(value)})
            for key,title in [('past_context','历史记忆与反思上下文'),('memory_note','记忆结算状态'),('portfolio_context','本次持仓上下文')]:
                if state.get(key):report['sections'].append({'title':title,'text':str(state[key])})
            report['coverage']=coverage
            report['full_core_output']=all(x['available'] for x in coverage)
            report['state']={key:state[key] for key in ('company_of_interest','trade_date','asset_type','market_report','sentiment_report','news_report','fundamentals_report','investment_debate_state','investment_plan','trader_investment_plan','risk_debate_state','final_trade_decision','final_rating','past_context','memory_note','portfolio_context') if key in state}
            report['sections'].append({'title':'数据与执行范围','text':'本报告调用原仓库完整代理图及其配置数据源；不以网页已下载日线冒充新闻、基本面或情绪证据。评级不是实盘指令。未输出的角色在覆盖表中明确标记。'})
    report['source_integrity']=integrity()
    atomic_json(output,report)
    return report
