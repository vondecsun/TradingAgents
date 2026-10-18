"""Account isolation, ledger invariants, quota races and billing authenticity."""
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from product.server.app import app, RATE
from product.server import db


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('PRODUCT_DB',str(tmp_path/'db.sqlite3'))
    monkeypatch.setenv('PRODUCT_WORKER','false')
    monkeypatch.delenv('PRODUCT_TEST_BILLING',raising=False)
    monkeypatch.delenv('PRODUCT_INTERNAL_RESEARCH',raising=False)
    RATE.clear()
    with TestClient(app) as c:
        yield c


def signup(c,email='tester@example.com'):
    r=c.post('/api/v1/auth/register',json={'email':email,'password':'test-passphrase-2026'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}


def post(c,url,headers,data=None):
    return c.post('/api/v1'+url,headers=headers,json=data)


def get(c,url,headers):
    return c.get('/api/v1'+url,headers=headers)


def buy(c,h,key='buy-order-1',**kw):
    return post(c,'/paper/orders',h,{'symbol':'000001.SZ','side':'buy','quantity':100,'limit_price':'11','idempotency_key':key,**kw})


def test_auth_logout_and_cross_account_isolation(client):
    a=signup(client)
    b=signup(client,'second@example.com')
    assert client.get('/api/v1/me').status_code==401
    assert post(client,'/data/demo',a).status_code==200
    assert get(client,'/instruments',b).json()['items']==[]
    order=buy(client,a).json()
    assert post(client,f"/paper/orders/{order['id']}/cancel",b).status_code==400
    job=post(client,'/analysis-jobs',a,{'symbol':'000001.SZ','idempotency_key':'research-111'}).json()
    assert post(client,f"/analysis-jobs/{job['id']}/cancel",b).status_code==404
    assert post(client,'/auth/logout',a).status_code==200
    assert get(client,'/me',a).status_code==401


def test_money_reservation_t_plus_one_and_ledger(client):
    h=signup(client)
    post(client,'/data/demo',h)
    before=get(client,'/paper/account',h).json()
    first=buy(client,h)
    assert first.status_code==200,first.text
    repeat=buy(client,h)
    assert repeat.json()['id']==first.json()['id']
    assert buy(client,h,quantity=200).status_code==400
    reserved=get(client,'/paper/account',h).json()
    assert reserved['cash']==before['cash']
    assert reserved['reserved']==110500
    assert post(client,'/paper/advance',h).status_code==200
    filled=get(client,'/paper/account',h).json()
    p=next(p for p in filled['positions'] if p['symbol']=='000001.SZ')
    assert p['quantity']==100 and p['available']==0
    assert filled['reserved']==0
    assert buy(client,h,key='sell-order-1',side='sell',limit_price='9').status_code==400
    post(client,'/paper/advance',h)
    assert buy(client,h,key='sell-order-2',side='sell',limit_price='9').status_code==200
    assert buy(client,h,key='sell-order-3',side='sell',limit_price='9').status_code==400
    post(client,'/paper/advance',h)
    result=get(client,'/paper/account',h).json()
    hist=get(client,'/paper/history',h).json()
    assert result['positions']==[]
    assert sum(x['amount'] for x in hist['ledger'])==result['cash']
    assert len(hist['fills'])==2


def test_cancel_releases_money_and_reject_overspend(client):
    h=signup(client)
    post(client,'/data/demo',h)
    assert buy(client,h,quantity=10000000).status_code==400
    r=buy(client,h).json()
    assert post(client,'/paper/orders/'+r['id']+'/cancel',h).status_code==200
    assert post(client,'/paper/orders/'+r['id']+'/cancel',h).status_code==200
    assert get(client,'/paper/account',h).json()['reserved']==0
    post(client,'/paper/advance',h)
    assert get(client,'/paper/history',h).json()['fills']==[]
    assert buy(client,h,key='nan-price',limit_price='NaN').status_code==400
    assert buy(client,h,key='float-qty',quantity=100.5).status_code==422


def test_no_lookahead_and_single_price_nonfill(client):
    h=signup(client)
    csv='symbol,date,open,high,low,close,volume,tradable\n000001.SZ,2025-01-02,10,11,9,10,1000,1\n000001.SZ,2025-01-03,10,10,10,10,1000,1\n'
    r=post(client,'/data/import',h,{'csv':csv,'source':'fixture licensed source'})
    assert r.status_code==200,r.text
    bars=get(client,'/instruments/000001.SZ/bars',h).json()['items']
    assert len(bars)==1
    assert buy(client,h).status_code==200
    post(client,'/paper/advance',h)
    hist=get(client,'/paper/history',h).json()
    assert not hist['fills'] and hist['orders'][0]['status']=='accepted'
    assert '无法证明' in hist['orders'][0]['reason']
    assert post(client,'/data/import',h,{'csv':csv,'source':'attempt overwrite'}).status_code==400
    assert post(client,'/paper/advance',h).status_code==400


def test_jobs_quota_and_cancellation(client):
    h=signup(client)
    post(client,'/data/demo',h)
    job={'symbol':'000001.SZ','idempotency_key':'job-unique-1'}
    a=post(client,'/analysis-jobs',h,job)
    assert a.status_code==202,a.text
    assert post(client,'/analysis-jobs',h,job).json()['id']==a.json()['id']
    assert post(client,'/analysis-jobs',h,{**job,'symbol':'600519.SH'}).status_code==409
    assert get(client,'/subscription',h).json()['current']['used']==1
    assert post(client,'/paper/reset',h,{'confirmation':'RESET SIMULATION'}).status_code==400
    post(client,'/analysis-jobs/'+a.json()['id']+'/cancel',h)
    assert get(client,'/subscription',h).json()['current']['used']==0
    assert post(client,'/analysis-jobs',h,{**job,'idempotency_key':'internal-1','engine':'tradingagents'}).status_code==403


def test_concurrent_orders_do_not_overspend(client):
    h=signup(client)
    post(client,'/data/demo',h)
    def submit(i):
        return buy(client,h,key='parallel-'+str(i),quantity=60000).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,range(2)))
    assert sorted(results)==[200,400]
    a=get(client,'/paper/account',h).json()
    assert a['available_cash']>=0


def test_billing_signature_amount_and_replay(client,monkeypatch):
    h=signup(client)
    assert post(client,'/subscription/test-activate',h,{'plan':'pro'}).status_code==403
    assert post(client,'/billing/orders',h,{'plan':'pro'}).status_code==503
    monkeypatch.setenv('PRODUCT_BILLING_WEBHOOK_SECRET','test-secret-never-production')
    with db.transaction() as con:
        uid=con.execute('SELECT id FROM users').fetchone()[0]
        con.execute('INSERT INTO billing_orders VALUES(?,?,?,?,?,?,?)',('order-1',uid,'pro',19900,'CNY','pending','2025-01-01'))
    def event(amount=19900,event_id='event-1',valid=True):
        raw=json.dumps({'id':event_id,'order_id':'order-1','amount':amount,'currency':'CNY','status':'paid'}).encode()
        stamp=str(int(time.time()))
        sig=hmac.new(b'test-secret-never-production',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest() if valid else 'forged'
        return client.post('/api/v1/billing/webhook',content=raw,headers={'Content-Type':'application/json','x-billing-timestamp':stamp,'x-billing-signature':sig})
    assert event(valid=False).status_code==401
    assert event(amount=1).status_code==409
    assert event().status_code==200
    expires=get(client,'/subscription',h).json()['current']['expires']
    assert event().json()['duplicate']
    assert event(event_id='event-2').status_code==200
    assert get(client,'/subscription',h).json()['current']['expires']==expires


def test_csv_validation_atomicity_and_demo_separation(client):
    h=signup(client)
    csv='symbol,date,open,high,low,close,volume,tradable\n000001.SZ,2025-01-02,10,9,11,10,100,1\n'
    assert post(client,'/data/import',h,{'csv':csv,'source':'my source'}).status_code==400
    assert get(client,'/instruments',h).json()['items']==[]
    post(client,'/data/demo',h)
    assert post(client,'/data/import',h,{'csv':csv,'source':'my source'}).status_code==400
    assert post(client,'/paper/reset',h,{'confirmation':'RESET SIMULATION'}).status_code==200
    assert get(client,'/instruments',h).json()['items']==[]


def test_worker_generates_report_and_durable_status(client):
    import threading
    from product.server.worker import work,recover
    h=signup(client)
    post(client,'/data/demo',h)
    job=post(client,'/analysis-jobs',h,{'symbol':'000001.SZ','idempotency_key':'worker-test'}).json()['id']
    stop=threading.Event()
    thread=threading.Thread(target=work,args=(stop,))
    thread.start()
    try:
        for _ in range(50):
            r=get(client,'/reports/'+job,h)
            if r.status_code==200:
                break
            time.sleep(.1)
        assert r.status_code==200,r.text
        report=r.json()
        assert report['mode']=='demo' and report['engine']=='facts'
        assert all(e['date']<=report['as_of'] for e in report['evidence'])
    finally:
        stop.set();thread.join(timeout=5)
    with db.transaction() as con:
        con.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
    recover()
    assert get(client,'/analysis-jobs',h).json()['items'][0]['status']=='failed'
    assert get(client,'/subscription',h).json()['current']['used']==0


def test_concurrent_quota_reservation(client):
    h=signup(client)
    post(client,'/data/demo',h)
    original=post(client,'/analysis-jobs',h,{'symbol':'000001.SZ','idempotency_key':'seed-quota'}).json()['id']
    with db.transaction() as con:
        con.execute("UPDATE jobs SET status='completed',cost=4 WHERE id=?",(original,))
    def submit(i):
        return post(client,'/analysis-jobs',h,{'symbol':'000001.SZ','idempotency_key':'concurrent-job-'+str(i)}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,range(2)))
    assert sorted(results)==[202,403]
    assert get(client,'/subscription',h).json()['current']['used']==5


def test_password_not_stored_raw_and_untrusted_source_is_data(client):
    from product.server.engine import run
    h=signup(client)
    source='<img src=x onerror=alert(1)>'
    data='symbol,date,open,high,low,close,volume,tradable\n000001.SZ,2025-01-02,10,11,9,10,1000,1\n'
    assert post(client,'/data/import',h,{'csv':data,'source':source}).status_code==200
    with db.transaction() as con:
        password=con.execute('SELECT password FROM users').fetchone()[0]
        tokens=[r[0] for r in con.execute('SELECT token FROM sessions')]
    assert 'test-passphrase-2026' not in password
    assert all(h['Authorization'][7:] != x for x in tokens)
    bars=get(client,'/instruments/000001.SZ/bars',h).json()['items']
    report=run({'bars':bars,'symbol':'000001.SZ','as_of':'2025-01-02','engine':'facts'})
    assert report['source']==source
    assert get(client,'/paper/history',h).json()['ledger'][0]['date']=='2025-01-02'
    response=client.get('/')
    assert "script-src 'self'" in response.headers['Content-Security-Policy']


def chart_fixture(symbol='000001.SZ'):
    return {'chart':{'error':None,'result':[{'meta':{'symbol':symbol.replace('.SH','.SS'),'currency':'CNY','shortName':'Fixture bank'},'timestamp':[1735781400,1735867800],'indicators':{'quote':[{'open':[10,10.1],'high':[10.2,10.3],'low':[9.9,10],'close':[10.1,10.2],'volume':[100000,120000]}]}}]}}


def mock_history(monkeypatch):
    from product.server import market
    calls=[]
    def fetch(symbol,start,end):
        calls.append(symbol)
        return market.parse_chart(chart_fixture(symbol),symbol,start,end)
    monkeypatch.setattr(market,'fetch_daily',fetch)
    return calls


def test_one_click_history_cache_and_no_paper_mutation(client,monkeypatch):
    h=signup(client)
    calls=mock_history(monkeypatch)
    before=get(client,'/paper/account',h).json()
    request={'symbol':'000001','start':'2025-01-02','end':'2025-01-03'}
    r=post(client,'/data/fetch',h,request)
    assert r.status_code==200,r.text
    assert r.json()['downloaded']==2 and r.json()['symbol']=='000001.SZ'
    assert get(client,'/paper/account',h).json()==before
    quotes=get(client,'/instruments',h).json()
    assert quotes['scope']=='online' and quotes['items'][0]['mode']=='online'
    assert quotes['items'][0]['watched']
    assert len(get(client,'/instruments/000001.SZ/bars',h).json()['items'])==2
    assert get(client,'/instruments?scope=paper',h).json()['items']==[]
    assert post(client,'/data/fetch',h,request).json()['cached']
    assert len(calls)==1
    job=post(client,'/analysis-jobs',h,{'symbol':'000001.SZ','idempotency_key':'online-snapshot'}).json()['id']
    with db.transaction() as con:
        snapshot=json.loads(con.execute('SELECT input FROM jobs WHERE id=?',(job,)).fetchone()[0])
    assert snapshot['as_of']=='2025-01-03' and len(snapshot['bars'])==2
    assert all(x['mode']=='online' for x in snapshot['bars'])


def test_history_does_not_destroy_demo_and_can_start_paper(client,monkeypatch):
    h=signup(client)
    mock_history(monkeypatch)
    post(client,'/data/demo',h)
    buy(client,h)
    before=get(client,'/paper/account',h).json()
    payload={'symbol':'000001','start':'2025-01-02','end':'2025-01-03'}
    assert post(client,'/data/fetch',h,payload).status_code==200
    assert get(client,'/paper/account',h).json()==before
    assert get(client,'/instruments',h).json()['scope']=='online'
    assert get(client,'/instruments?scope=paper',h).json()['items'][0]['mode']=='demo'
    assert post(client,'/data/use-for-paper',h,{'symbol':'000001'}).status_code==409
    post(client,'/paper/reset',h,{'confirmation':'RESET SIMULATION'})
    assert get(client,'/instruments',h).json()['items'][0]['mode']=='online'
    assert post(client,'/data/use-for-paper',h,{'symbol':'000001'}).status_code==200
    assert get(client,'/paper/account',h).json()['as_of']=='2025-01-02'
    assert len(get(client,'/instruments/000001.SZ/bars?scope=paper',h).json()['items'])==1
    assert buy(client,h).status_code==200
    assert post(client,'/paper/advance',h).status_code==200
    assert len(get(client,'/paper/history',h).json()['fills'])==1


def test_history_failure_and_validation_preserve_workspace(client,monkeypatch):
    from product.server import market
    h=signup(client)
    post(client,'/data/demo',h)
    before=get(client,'/instruments',h).json()
    def fail(*args):raise market.MarketError('provider_timeout','行情下载超时，请检查网络后重试')
    monkeypatch.setattr(market,'fetch_daily',fail)
    request={'symbol':'000001','start':'2025-01-02','end':'2025-01-03'}
    r=post(client,'/data/fetch',h,request)
    assert r.status_code==502 and r.json()['error']['code']=='provider_timeout'
    assert get(client,'/instruments',h).json()==before
    assert post(client,'/data/fetch',h,{**request,'symbol':'http://x'}).status_code==400
    assert post(client,'/data/fetch',h,{**request,'end':'2099-01-01'}).status_code==400
    assert post(client,'/data/fetch',h,{**request,'start':'2025-01-04'}).status_code==400
    assert post(client,'/data/fetch',h,{**request,'start':'bad'}).status_code==422


def test_history_cross_account_isolation(client,monkeypatch):
    a=signup(client);b=signup(client,'private-history@example.com')
    mock_history(monkeypatch)
    assert post(client,'/data/fetch',a,{'symbol':'600519','start':'2025-01-02','end':'2025-01-03'}).status_code==200
    assert get(client,'/instruments',b).json()['items']==[]
    assert get(client,'/instruments/600519.SH/bars',b).json()['items']==[]
    assert post(client,'/data/use-for-paper',b,{'symbol':'600519'}).status_code==400


def test_chart_adapter_validation_and_fixed_destination(monkeypatch):
    from datetime import date
    from product.server import market
    result=market.parse_chart(chart_fixture(),'000001.SZ',date(2025,1,2),date(2025,1,3))
    assert len(result['items'])==2 and result['items'][0]['close']=='10.1000'
    bad=chart_fixture('600519.SH')
    with pytest.raises(market.MarketError):
        market.parse_chart(bad,'000001.SZ',date(2025,1,2),date(2025,1,3))
    bad=chart_fixture();bad['chart']['result'][0]['indicators']['quote'][0]['high'][0]=1
    with pytest.raises(market.MarketError):
        market.parse_chart(bad,'000001.SZ',date(2025,1,2),date(2025,1,3))
    bad=chart_fixture();bad['chart']['result'][0]['indicators']['quote'][0]['close'].pop()
    with pytest.raises(market.MarketError):
        market.parse_chart(bad,'000001.SZ',date(2025,1,2),date(2025,1,3))
    urls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,*args):return json.dumps(chart_fixture('600519.SH')).encode()
    def opener(request,timeout):
        urls.append(request.full_url);assert timeout==12;return Response()
    monkeypatch.setattr(market,'urlopen',opener)
    assert market.fetch_daily('600519.SH',date(2025,1,2),date(2025,1,3))['items']
    assert urls[0].startswith('https://query1.finance.yahoo.com/v8/finance/chart/600519.SS?')


def test_schema_upgrade_keeps_existing_paper_account(client):
    h=signup(client)
    post(client,'/data/demo',h)
    buy(client,h)
    before=get(client,'/paper/account',h).json()
    with db.transaction() as con:
        con.execute('DROP TABLE market_bars')
        con.execute('DROP TABLE market_fetches')
    db.init()
    assert get(client,'/paper/account',h).json()==before
    assert len(get(client,'/paper/history',h).json()['orders'])==1


def test_native_settings_snapshot_portfolio_and_resume_api(client,monkeypatch):
    from product.server import native
    h=signup(client)
    monkeypatch.setenv('PRODUCT_INTERNAL_RESEARCH','true')
    monkeypatch.setenv('PRODUCT_INTERNAL_EMAILS','tester@example.com')
    monkeypatch.setattr(native,'require_ready',lambda settings:None)
    config=get(client,'/research/config',h).json()
    assert config['authorized'] and config['source_integrity']['unchanged']
    settings=config['settings'];settings['max_debate_rounds']=2
    assert client.put('/api/v1/research/config',headers=h,json=settings).status_code==200
    request={'symbol':'000001.SZ','engine':'tradingagents','analysis_date':'2026-01-09','portfolio':{'cash':1000,'currency':'CNY','positions':[]},'idempotency_key':'native-api-snapshot'}
    r=post(client,'/analysis-jobs',h,request)
    assert r.status_code==202,r.text
    jid=r.json()['id']
    with db.transaction() as con:
        stored=json.loads(con.execute('SELECT input FROM jobs WHERE id=?',(jid,)).fetchone()[0])
        con.execute("UPDATE jobs SET status='failed',cost=0 WHERE id=?",(jid,))
    assert stored['research_settings']['max_debate_rounds']==2
    assert stored['as_of']=='2026-01-09' and stored['portfolio']['positions']==[]
    assert stored['_job_id']==jid
    assert post(client,'/analysis-jobs',h,{**request,'analysis_date':'2026-01-08'}).status_code==409
    assert post(client,'/research/jobs/'+jid+'/resume',h).status_code==202
    assert get(client,'/subscription',h).json()['current']['used']==1
    other=signup(client,'native-other@example.com')
    monkeypatch.setenv('PRODUCT_INTERNAL_EMAILS','tester@example.com,native-other@example.com')
    assert post(client,'/research/jobs/'+jid+'/resume',other).status_code==404
    assert get(client,'/research/jobs/'+jid+'/artifact?format=html',other).status_code==404


def test_native_batch_costs_permissions_and_missing_credentials(client,monkeypatch):
    from product.server import native
    h=signup(client)
    payload={'tickers':['000001.SZ'],'start':'2026-01-02','end':'2026-01-05','every_n_days':1,'idempotency_key':'native-batch-api'}
    assert post(client,'/research/backtests',h,payload).status_code==403
    monkeypatch.setenv('PRODUCT_INTERNAL_RESEARCH','true')
    monkeypatch.setenv('PRODUCT_INTERNAL_EMAILS','tester@example.com')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    assert post(client,'/analysis-jobs',h,{'symbol':'000001.SZ','engine':'tradingagents','idempotency_key':'missing-credentials'}).status_code==400
    assert get(client,'/analysis-jobs',h).json()['items']==[]
    monkeypatch.setattr(native,'require_ready',lambda settings:None)
    r=post(client,'/research/backtests',h,payload)
    assert r.status_code==202,r.text
    assert get(client,'/subscription',h).json()['current']['used']==4
    assert post(client,'/research/backtests',h,payload).json()['id']==r.json()['id']
    assert post(client,'/research/backtests',h,{**payload,'idempotency_key':'large-batch','end':'2026-02-28'}).status_code==400
    assert post(client,'/research/settlement',h,{'idempotency_key':'settlement-api'}).status_code==202
