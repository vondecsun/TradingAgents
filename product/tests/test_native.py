"""Exercise the original graph/agents offline; never emulate them in product code."""
import json
import pytest
from product.server import native
from product.server.engine import run


@pytest.fixture
def upstream_offline(monkeypatch,tmp_path):
    # Reuse the source repository's scripted model/vendor fixtures. Every real
    # graph node, router, debate, manager, memory writer and report writer runs.
    from tests.test_graph_end_to_end import offline,ScriptedModel,_Client,ARGS
    from tradingagents.graph import trading_graph
    from tradingagents.memory import settlement
    import socket
    def no_network(*a,**k):raise OSError('network forbidden in offline integration test')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    monkeypatch.setattr(socket,'getaddrinfo',no_network)
    called=offline.__wrapped__(monkeypatch,tmp_path)
    monkeypatch.setenv('PRODUCT_RESEARCH_DIR',str(tmp_path/'native'))
    monkeypatch.setitem(ARGS,'symbol','000001.SZ');monkeypatch.setitem(ARGS,'ticker','000001.SZ')
    model=ScriptedModel(structured=True)
    monkeypatch.setattr(trading_graph,'create_tier_client',lambda config,tier,**k:_Client(model))
    # Fixed, explicitly synthetic return fixture; no market performance claim.
    monkeypatch.setattr(settlement,'fetch_returns',lambda *a,**k:(.01,.005,5,'2026-01-16'))
    return model,called


def payload(engine='tradingagents',jid='b'*32):
    return {'engine':engine,'_user_id':'a'*32,'_job_id':jid,'research_settings':native.defaults(),'symbol':'000001.SZ','as_of':'2026-01-09','portfolio':{'cash':25000,'currency':'CNY','positions':[{'ticker':'000001.SZ','quantity':100,'average_price':10}]}}


def test_original_full_graph_all_roles_reports_and_memory(upstream_offline):
    model,called=upstream_offline
    report=run(payload())
    assert report['native'] and report['rating']=='Overweight'
    assert report['full_core_output']
    assert len(report['coverage'])==12
    assert all(x['available'] for x in report['coverage'])
    for key in ('sentiment_report','investment_debate_state','risk_debate_state','trader_investment_plan','final_trade_decision','portfolio_context'):
        assert report['state'][key]
    assert report['settings']['analysts']==native.ANALYSTS
    assert '100' in report['state']['portfolio_context']
    assert {'get_news','get_fundamentals','get_indicators','get_stock_data','get_global_news','get_macro_indicators','get_prediction_markets'}<=called
    folder=native.job_root('a'*32,'b'*32)
    assert (folder/'reports'/'complete_report.html').is_file()
    assert (folder/'reports'/'complete_report.md').is_file()
    assert (folder/'result.json').is_file()
    memory=native.tenant_root('a'*32)/'memory'/'trading_memory.md'
    assert 'Overweight' in memory.read_text()
    assert not (native.tenant_root('c'*32)/'memory'/'trading_memory.md').exists()
    calls=len(model.calls)
    assert run(payload())==report
    assert len(model.calls)==calls, 'completed result reuse must not call the models again'
    assert report['source_integrity']['unchanged']


def test_original_checkpoint_survives_product_retry(upstream_offline,monkeypatch):
    from tests.test_graph_end_to_end import ScriptedModel,_Client
    from tradingagents.graph import trading_graph
    model=ScriptedModel(fail_at=12)
    monkeypatch.setattr(trading_graph,'create_tier_client',lambda config,tier,**k:_Client(model))
    with pytest.raises(RuntimeError,match='provider unavailable'):
        run(payload(jid='d'*32))
    folder=native.job_root('a'*32,'d'*32)
    assert list((folder/'checkpoints').rglob('*.db'))
    before=len(model.calls)
    resumed=run(payload(jid='d'*32))
    assert resumed['rating']=='Overweight'
    resumed_calls=len(model.calls)-before
    fresh=ScriptedModel()
    monkeypatch.setattr(trading_graph,'create_tier_client',lambda config,tier,**k:_Client(fresh))
    run(payload(jid='e'*32))
    assert resumed_calls < len(fresh.calls)


def test_original_backtest_and_settlement_apis(upstream_offline):
    batch=payload(engine='backtest',jid='f'*32)
    batch.update(tickers=['000001.SZ'],dates=['2026-01-08','2026-01-09'])
    result=run(batch)
    assert result['backtest']['cells_run']==2
    assert not result['backtest']['failures']
    assert result['backtest']['summary']['resolved']==2
    # Backtest's original private log must not flood the live tenant memory.
    assert not (native.tenant_root('a'*32)/'memory'/'trading_memory.md').exists()
    run(payload())
    settled=run(payload(engine='settlement',jid='1'*32))
    assert settled['settlement']['settled']
    assert settled['settlement']['entries'][0]['reflection']


def test_safe_settings_and_tenant_paths():
    assert native.integrity()['checked_files']>=90
    with pytest.raises(ValueError):native.tenant_root('../../etc')
    with pytest.raises(ValueError):native.job_root('a'*32,'../x')
    with pytest.raises(ValueError):native.ResearchSettings(backend_url='http://untrusted')
    with pytest.raises(ValueError):native.ResearchSettings(analysts=['market','market'])
    with pytest.raises(ValueError):native.ResearchSettings(llm_provider='invented')
    settings=native.ResearchSettings(llm_provider='deepseek',quick_think_llm='deepseek-chat',deep_think_llm='deepseek-reasoner')
    assert settings.model_dump()['analysts']==native.ANALYSTS


def test_missing_market_data_stops_before_any_model_call(upstream_offline,monkeypatch):
    from tradingagents.dataflows import router
    model,called=upstream_offline
    monkeypatch.setattr(router,'route_to_vendor',lambda *a,**k:'DATA_UNAVAILABLE: synthetic source failure')
    with pytest.raises(ValueError,match='market_data_unavailable'):
        run(payload(jid='e'*32))
    assert model.calls==[]
