"""A-share product pilot API. Single-host / single-worker deployment only."""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from . import db, paper, worker

PREFIX = '/api/v1'
PLANS = {'free': {'quota': 5, 'price': 0}, 'research': {'quota': 100, 'price': 9900}, 'pro': {'quota': 500, 'price': 19900}}
WEB = Path(__file__).resolve().parents[1] / 'web'
RATE = defaultdict(deque)
RATE_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def epoch():
    return int(time.time())


def period():
    return datetime.now(timezone.utc).strftime('%Y-%m')


def error(code, message, status=400):
    raise HTTPException(status, detail={'code': code, 'message': message})


def audit(con, user, action, detail=''):
    con.execute('INSERT INTO audit(user_id,action,detail,created) VALUES(?,?,?,?)', (user, action, detail, now()))


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()
    return salt + ':' + digest


def test_billing():
    return os.getenv('PRODUCT_TEST_BILLING', 'false').lower() == 'true'


def internal(email):
    return os.getenv('PRODUCT_INTERNAL_RESEARCH', 'false').lower() == 'true' and email in os.getenv('PRODUCT_INTERNAL_EMAILS', '').split(',')


def user(authorization: str = Header(default='')):
    if not authorization.startswith('Bearer '):
        error('auth_required', '请先登录', 401)
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with db.transaction() as con:
        row = con.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?', (digest, epoch())).fetchone()
    if not row:
        error('session_expired', '登录已过期，请重新登录', 401)
    return dict(row)


def subscription(con, uid):
    row = con.execute('SELECT * FROM subscriptions WHERE user_id=?', (uid,)).fetchone()
    plan = row['plan'] if row and row['expires'] > epoch() else 'free'
    used = con.execute('SELECT COALESCE(SUM(cost),0) FROM jobs WHERE user_id=? AND period=?', (uid, period())).fetchone()[0]
    return {'plan': plan, 'quota': PLANS[plan]['quota'], 'used': used, 'remaining': max(0, PLANS[plan]['quota']-used), 'expires': row['expires'] if row else None, 'mode': row['mode'] if row and plan != 'free' else 'free', 'period': period()}


@asynccontextmanager
async def lifespan(app):
    db.init()
    worker.recover()
    stop = threading.Event()
    thread = threading.Thread(target=worker.work, args=(stop,), daemon=True)
    if os.getenv('PRODUCT_WORKER', 'true') == 'true':
        thread.start()
    yield
    stop.set()
    if thread.is_alive():
        thread.join(timeout=5)


app = FastAPI(title='衡研 · A股研究工作台', version='0.1.0', lifespan=lifespan)
origins = [x.strip() for x in os.getenv('PRODUCT_CORS_ORIGINS', '').split(',') if x.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST','DELETE'], allow_headers=['Authorization','Content-Type'])


@app.middleware('http')
async def guard(request, call_next):
    request_id = uuid.uuid4().hex
    if request.method in ('POST', 'PUT', 'PATCH'):
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > 2000000):
            return JSONResponse({'error': {'code':'body_too_large','message':'请求超过2MB限制'}, 'request_id':request_id}, 413)
        if len(await request.body()) > 2000000:
            return JSONResponse({'error': {'code':'body_too_large','message':'请求超过2MB限制'}, 'request_id':request_id}, 413)
    response = await call_next(request)
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' " + ' '.join(origins) + "; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'error': {'code':'invalid_operation','message':str(exc)}}, status_code=400)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    detail = exc.detail if isinstance(exc.detail, dict) else {'code':'request_failed','message':str(exc.detail)}
    return JSONResponse({'error':detail}, status_code=exc.status_code)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Credentials(Model):
    email: str = Field(min_length=3,max_length=200)
    password: str = Field(min_length=12,max_length=200)


def rate_limit(request):
    key = request.client.host if request.client else 'local'
    with RATE_LOCK:
        q = RATE[key]
        while q and q[0] < time.monotonic()-60:
            q.popleft()
        if len(q) >= 12:
            error('rate_limit','登录/注册请求过多，请一分钟后重试',429)
        q.append(time.monotonic())
        # Bound memory, never depend on client-supplied forwarded IPs.
        if len(RATE) > 10000:
            for k in list(RATE):
                if not RATE[k] or RATE[k][-1] < time.monotonic()-60:
                    del RATE[k]


def make_session(con, uid):
    token = secrets.token_urlsafe(32)
    con.execute('DELETE FROM sessions WHERE expires<=?',(epoch(),))
    con.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,epoch()+28800))
    return {'token':token,'expires_in':28800}


@app.post(PREFIX+'/auth/register')
def register(data: Credentials, request: Request):
    rate_limit(request)
    email = data.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        error('invalid_email','请输入有效邮箱')
    uid = uuid.uuid4().hex
    hashed = password_hash(data.password)
    with db.transaction() as con:
        if con.execute('SELECT 1 FROM users WHERE email=?',(email,)).fetchone():
            error('registration_failed','邮箱不可用于注册')
        con.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,email,hashed,now()))
        today = date.today().isoformat()
        con.execute('INSERT INTO accounts VALUES(?,?,?,?)',(uid,100000000,today,100000000))
        con.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,uid,today,'initial',100000000,100000000,'virtual_initial_capital'))
        audit(con,uid,'register')
        return make_session(con,uid)


@app.post(PREFIX+'/auth/login')
def login(data: Credentials, request: Request):
    rate_limit(request)
    with db.transaction() as con:
        row = con.execute('SELECT * FROM users WHERE email=?',(data.email.strip().lower(),)).fetchone()
    stored = row['password'] if row else password_hash('dummy-password-value', '0'*32)
    valid = hmac.compare_digest(password_hash(data.password,stored.split(':')[0]),stored)
    if not row or not valid:
        error('invalid_credentials','邮箱或密码错误',401)
    with db.transaction() as con:
        return make_session(con,row['id'])


@app.post(PREFIX+'/auth/logout')
def logout(u=Depends(user), authorization: str=Header(default='')):
    with db.transaction() as con:
        con.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(authorization[7:].encode()).hexdigest(),))
    return {'ok':True}


@app.get(PREFIX+'/health')
def health():
    with db.transaction() as con:
        con.execute('SELECT 1')
    return {'status':'ok','version':'0.1.0','live_trading':False}


@app.get(PREFIX+'/me')
def me(u=Depends(user)):
    with db.transaction() as con:
        return {'email':u['email'],'subscription':subscription(con,u['id']), 'internal_research':internal(u['email']), 'test_billing':test_billing(), 'live_trading':False, 'broker':{'name':'国金证券','status':'not_configured','reason':'官方接口、账户权限及商业授权尚未核实'}, 'data_provider':'用户CSV/明确标识的演示数据；无实时行情连接'}


@app.get(PREFIX+'/instruments')
def instruments(u=Depends(user)):
    with db.transaction() as con:
        day = con.execute('SELECT as_of FROM accounts WHERE user_id=?',(u['id'],)).fetchone()[0]
        rows = con.execute('SELECT b.* FROM bars b JOIN (SELECT symbol,MAX(date) day FROM bars WHERE user_id=? AND date<=? GROUP BY symbol) x ON b.symbol=x.symbol AND b.date=x.day WHERE b.user_id=? ORDER BY b.symbol',(u['id'],day,u['id'])).fetchall()
        watches = {r[0] for r in con.execute('SELECT symbol FROM watchlist WHERE user_id=?',(u['id'],))}
        return {'as_of':day,'items':[{**dict(r),'watched':r['symbol'] in watches} for r in rows]}


@app.get(PREFIX+'/instruments/{symbol}/bars')
def bars(symbol: str,u=Depends(user)):
    with db.transaction() as con:
        as_of = con.execute('SELECT as_of FROM accounts WHERE user_id=?',(u['id'],)).fetchone()[0]
        return {'items':[dict(r) for r in con.execute('SELECT * FROM bars WHERE user_id=? AND symbol=? AND date<=? ORDER BY date DESC LIMIT 250',(u['id'],symbol,as_of))][::-1], 'as_of':as_of}


@app.post(PREFIX+'/watchlist/{symbol}')
def watch(symbol: str,u=Depends(user)):
    if not paper.symbol_ok(symbol):
        error('unsupported_symbol','证券代码不支持')
    with db.transaction() as con:
        con.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?)',(u['id'],symbol))
    return {'ok':True}


@app.delete(PREFIX+'/watchlist/{symbol}')
def unwatch(symbol: str,u=Depends(user)):
    with db.transaction() as con:
        con.execute('DELETE FROM watchlist WHERE user_id=? AND symbol=?',(u['id'],symbol))
    return {'ok':True}


class ImportData(Model):
    csv: str = Field(max_length=1500000)
    source: str = Field(min_length=2,max_length=150)


@app.post(PREFIX+'/data/import')
def import_data(data: ImportData,u=Depends(user)):
    reader = csv.DictReader(io.StringIO(data.csv.lstrip('\ufeff')))
    required = {'symbol','date','open','high','low','close','volume','tradable'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        error('csv_header','CSV需包含 symbol,date,open,high,low,close,volume,tradable')
    records = []
    seen = set()
    for index, row in enumerate(reader):
        if index >= 10000:
            error('csv_limit','每次最多10000行')
        if not paper.symbol_ok(row['symbol']):
            error('csv_symbol',f'第{index+2}行证券不支持')
        day = date.fromisoformat(row['date'])
        if day.isoformat() != row['date'] or day > date.today() or day.weekday() >= 5:
            error('csv_date',f'第{index+2}行日期无效；交易所节假日需由数据源确保')
        prices = [paper.price(row[k]) for k in ('open','high','low','close')]
        o,h,l,c = prices
        if l > min(o,c) or h < max(o,c) or h < l:
            error('csv_ohlc',f'第{index+2}行OHLC关系错误')
        if not row['volume'].isdigit() or int(row['volume']) > 10**15 or row['tradable'] not in ('0','1'):
            error('csv_values',f'第{index+2}行成交量或可交易标记无效')
        key = (row['symbol'],row['date'])
        if key in seen:
            error('csv_duplicate','CSV内有重复证券日期')
        seen.add(key)
        records.append((u['id'],row['symbol'],row['date'],*[str(p) for p in prices],int(row['volume']),data.source,'imported',int(row['tradable'])))
    if not records:
        error('csv_empty','CSV为空')
    with db.transaction() as con:
        if con.execute("SELECT 1 FROM bars WHERE user_id=? AND mode='demo'",(u['id'],)).fetchone():
            error('demo_isolation','当前为演示账户数据，请先重置模拟工作区后导入')
        for r in records:
            if con.execute('SELECT 1 FROM bars WHERE user_id=? AND symbol=? AND date=?',r[:3]).fetchone():
                error('immutable_snapshot','已有日线不可覆盖，请使用新的账户工作区')
        if not con.execute('SELECT 1 FROM bars WHERE user_id=?',(u['id'],)).fetchone():
            first = min(r[2] for r in records)
            con.execute('UPDATE accounts SET as_of=? WHERE user_id=?',(first,u['id']))
            con.execute("UPDATE ledger SET date=? WHERE user_id=? AND kind='initial'",(first,u['id']))
        con.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?)',records)
        audit(con,u['id'],'data_import',str(len(records)))
    return {'imported':len(records),'mode':'imported','verified':False}


@app.post(PREFIX+'/data/demo')
def demo(u=Depends(user)):
    with db.transaction() as con:
        if con.execute('SELECT 1 FROM bars WHERE user_id=?',(u['id'],)).fetchone():
            error('workspace_not_empty','仅空工作区可载入演示数据')
        days = []
        cursor = date(2025,1,2)
        while len(days) < 35:
            if cursor.weekday() < 5:
                days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        for j,symbol in enumerate(['600519.SH','000001.SZ','600036.SH']):
            base = [1400,10,35][j]
            for i,day in enumerate(days):
                o = paper.D(str(base)) * (paper.D('1') + paper.D(i%9-3)/1000 + paper.D(i)/2000)
                c = o * (paper.D('1.004') if i%3 else paper.D('0.997'))
                vals = [o,max(o,c)*paper.D('1.005'),min(o,c)*paper.D('0.995'),c]
                con.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?,?,?)',(u['id'],symbol,day,*[str(x.quantize(paper.D('.01'))) for x in vals],1000000+i*10000,'合成演示数据，非历史真实行情','demo',1))
            con.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?)',(u['id'],symbol))
        con.execute('UPDATE accounts SET as_of=? WHERE user_id=?',(days[5],u['id']))
        con.execute("UPDATE ledger SET date=? WHERE user_id=? AND kind='initial'",(days[0],u['id']))
        audit(con,u['id'],'load_demo')
    return {'ok':True,'mode':'demo'}


class Reset(Model):
    confirmation: Literal['RESET SIMULATION']


@app.post(PREFIX+'/paper/reset')
def reset(data: Reset,u=Depends(user)):
    with db.transaction() as con:
        if con.execute("SELECT 1 FROM jobs WHERE user_id=? AND status IN ('queued','running')",(u['id'],)).fetchone():
            error('active_jobs','请先完成或取消分析任务')
        for table in ('bars','watchlist','orders','fills','ledger'):
            con.execute(f'DELETE FROM {table} WHERE user_id=?',(u['id'],))
        today = date.today().isoformat()
        con.execute('UPDATE accounts SET cash=initial_cash,as_of=? WHERE user_id=?',(today,u['id']))
        con.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,u['id'],today,'initial',100000000,100000000,'reset_virtual_capital'))
        audit(con,u['id'],'reset_simulation')
    return {'ok':True}


@app.get(PREFIX+'/paper/account')
def paper_account(u=Depends(user)):
    with db.transaction() as con:
        return paper.account(con,u['id'])


class Order(Model):
    symbol: str = Field(max_length=12)
    side: Literal['buy','sell']
    quantity: StrictInt
    limit_price: str = Field(max_length=25)
    idempotency_key: str = Field(min_length=8,max_length=100)


@app.post(PREFIX+'/paper/orders')
def order(data: Order,u=Depends(user)):
    with db.transaction() as con:
        result = paper.submit(con,u['id'],data.model_dump())
        audit(con,u['id'],'paper_order',result['id'])
        return result


@app.post(PREFIX+'/paper/orders/{oid}/cancel')
def cancel_order(oid: str,u=Depends(user)):
    with db.transaction() as con:
        paper.cancel(con,u['id'],oid)
        audit(con,u['id'],'paper_cancel',oid)
    return {'ok':True}


@app.post(PREFIX+'/paper/advance')
def advance(u=Depends(user)):
    with db.transaction() as con:
        result = paper.advance(con,u['id'])
        audit(con,u['id'],'paper_advance',result['as_of'])
        return result


@app.get(PREFIX+'/paper/history')
def history(u=Depends(user)):
    with db.transaction() as con:
        return {t:[dict(r) for r in con.execute(f'SELECT * FROM {t} WHERE user_id=? ORDER BY rowid DESC LIMIT 200',(u['id'],))] for t in ('orders','fills','ledger')}


class Job(Model):
    symbol: str = Field(max_length=12)
    engine: Literal['facts','tradingagents'] = 'facts'
    idempotency_key: str = Field(min_length=8,max_length=100)


@app.post(PREFIX+'/analysis-jobs',status_code=202)
def create_job(data: Job,u=Depends(user)):
    if data.engine == 'tradingagents' and not internal(u['email']):
        error('internal_only','真实多代理研究仅供获准内部测试账户',403)
    with db.transaction() as con:
        old = con.execute('SELECT * FROM jobs WHERE user_id=? AND idem=?',(u['id'],data.idempotency_key)).fetchone()
        if old:
            if old['symbol'] != data.symbol or old['engine'] != data.engine:
                error('idempotency_conflict','同一幂等键不能创建不同任务',409)
            return {'id':old['id'],'status':old['status']}
        ent = subscription(con,u['id'])
        if not ent['remaining']:
            error('quota_exhausted','本月分析额度已用完',403)
        if con.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')",(u['id'],)).fetchone()[0] >= 2:
            error('queue_limit','最多同时保留两个未完成任务',429)
        as_of = con.execute('SELECT as_of FROM accounts WHERE user_id=?',(u['id'],)).fetchone()[0]
        rows = [dict(r) for r in con.execute('SELECT * FROM bars WHERE user_id=? AND symbol=? AND date<=? ORDER BY date DESC LIMIT 250',(u['id'],data.symbol,as_of))][::-1]
        if not rows:
            error('no_data','请先载入演示或导入此证券的数据')
        if data.engine == 'tradingagents' and rows[-1]['mode'] == 'demo':
            error('demo_research','演示数据不可用于真实多代理研究')
        for row in rows:
            row.pop('user_id',None)
        jid = uuid.uuid4().hex
        payload = json.dumps({'bars':rows,'symbol':data.symbol,'as_of':as_of,'engine':data.engine},ensure_ascii=False)
        con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(jid,u['id'],data.idempotency_key,data.symbol,data.engine,'queued','排队等待',now(),now(),None,None,period(),1,0,payload))
        audit(con,u['id'],'analysis_created',jid)
        return {'id':jid,'status':'queued'}


@app.get(PREFIX+'/analysis-jobs')
def jobs(u=Depends(user)):
    with db.transaction() as con:
        return {'items':[dict(r) for r in con.execute('SELECT id,symbol,engine,status,stage,created,updated,error,cost FROM jobs WHERE user_id=? ORDER BY created DESC LIMIT 100',(u['id'],))]}


@app.get(PREFIX+'/reports/{jid}')
def report(jid: str,u=Depends(user)):
    with db.transaction() as con:
        row = con.execute('SELECT report,engine FROM jobs WHERE id=? AND user_id=? AND status=?',(jid,u['id'],'completed')).fetchone()
        if not row:
            error('report_not_found','报告不存在或尚未完成',404)
        if row['engine'] == 'tradingagents' and not internal(u['email']):
            error('internal_only','此报告仅供内部研究',403)
        return json.loads(row['report'])


@app.post(PREFIX+'/analysis-jobs/{jid}/cancel')
def cancel_job(jid: str,u=Depends(user)):
    with db.transaction() as con:
        row = con.execute('SELECT status FROM jobs WHERE id=? AND user_id=?',(jid,u['id'])).fetchone()
        if not row:
            error('job_not_found','任务不存在',404)
        if row['status'] == 'queued':
            con.execute("UPDATE jobs SET status='cancelled',stage='已取消',cost=0,cancel=1,updated=? WHERE id=?",(now(),jid))
        elif row['status'] == 'running':
            con.execute("UPDATE jobs SET cancel=1,stage='正在取消',updated=? WHERE id=?",(now(),jid))
        else:
            error('job_terminal','任务已经结束',409)
    return {'ok':True}


class Plan(Model):
    plan: Literal['research','pro']


@app.get(PREFIX+'/subscription')
def get_subscription(u=Depends(user)):
    with db.transaction() as con:
        return {'current':subscription(con,u['id']),'plans':PLANS,'test_billing':test_billing(),'checkout_enabled':False,'price_note':'套餐价格为开发测试配置，未开放销售'}


@app.post(PREFIX+'/subscription/test-activate')
def activate(data: Plan,u=Depends(user)):
    if not test_billing():
        error('test_billing_disabled','此环境未开放测试套餐激活',403)
    with db.transaction() as con:
        con.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?)',(u['id'],data.plan,epoch()+30*86400,'test'))
        audit(con,u['id'],'test_subscription',data.plan)
    return {'ok':True,'mode':'test','charged':False}


@app.post(PREFIX+'/billing/orders')
def billing_order(data: Plan,u=Depends(user)):
    error('checkout_not_configured','真实商户支付与销售权限尚未配置，不能购买',503)


@app.post(PREFIX+'/billing/webhook')
async def webhook(request: Request):
    # Adapter contract only: NOT advertised as WeChat/Alipay native verification.
    secret = os.getenv('PRODUCT_BILLING_WEBHOOK_SECRET','')
    if not secret:
        error('billing_unconfigured','支付回调未配置',503)
    raw = await request.body()
    stamp = request.headers.get('x-billing-timestamp','')
    if not stamp.isdigit() or abs(epoch()-int(stamp)) > 300:
        error('invalid_timestamp','支付通知已过期',401)
    signature = hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,request.headers.get('x-billing-signature','')):
        error('bad_signature','支付通知签名无效',401)
    try:
        event = json.loads(raw)
        if not isinstance(event,dict) or set(event) != {'id','order_id','status','amount','currency'} or not isinstance(event['id'],str) or not 1 <= len(event['id']) <= 150 or type(event['amount']) is not int:
            raise ValueError()
    except (ValueError,TypeError):
        error('bad_event','支付通知格式无效')
    with db.transaction() as con:
        old = con.execute('SELECT order_id FROM billing_events WHERE id=?',(event['id'],)).fetchone()
        if old:
            if old['order_id'] != event['order_id']:
                error('event_conflict','支付事件冲突',409)
            return {'ok':True,'duplicate':True}
        order = con.execute('SELECT * FROM billing_orders WHERE id=?',(event['order_id'],)).fetchone()
        if not order or order['amount'] != event['amount'] or order['currency'] != event['currency'] or event['status'] != 'paid':
            error('payment_mismatch','支付订单或金额不匹配',409)
        con.execute('INSERT INTO billing_events VALUES(?,?,?)',(event['id'],order['id'],now()))
        if order['status'] != 'paid':
            current = con.execute('SELECT expires FROM subscriptions WHERE user_id=?',(order['user_id'],)).fetchone()
            expires = max(epoch(),current['expires'] if current else 0)+30*86400
            con.execute('INSERT OR REPLACE INTO subscriptions VALUES(?,?,?,?)',(order['user_id'],order['plan'],expires,'paid'))
            con.execute("UPDATE billing_orders SET status='paid' WHERE id=?",(order['id'],))
            audit(con,order['user_id'],'billing_paid',order['id'])
    return {'ok':True}


@app.get(PREFIX+'/audit')
def audit_log(u=Depends(user)):
    with db.transaction() as con:
        return {'items':[dict(r) for r in con.execute('SELECT action,detail,created FROM audit WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],))]}


@app.get(PREFIX+'/announcements')
def announcements(u=Depends(user)):
    return {'items':[],'status':'not_configured','message':'尚未接入有商业授权的公告数据源，不生成虚构公告'}


app.mount('/assets',StaticFiles(directory=WEB),name='assets')


@app.get('/')
def index():
    return FileResponse(WEB/'index.html')
