"""Conservative daily-bar paper exchange; no live-broker order methods."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import uuid

D = Decimal
# Simulation assumptions, NOT current statutory fees or broker pricing.
FEE_RATE = D('0.001')
MIN_FEE = 500


def fail(message):
    raise ValueError(message)


def symbol_ok(symbol):
    return bool(re.fullmatch(r'(?:60[0135]\d{3}\.SH|00[012]\d{3}\.SZ)', symbol))


def price(value):
    try:
        p = D(str(value))
        if not p.is_finite() or p <= 0 or p > 1000000 or p.as_tuple().exponent < -4:
            fail('价格须为正数，最多四位小数')
        return p
    except InvalidOperation:
        fail('价格格式错误')


def money(value):
    return int((value * 100).quantize(D('1'), rounding=ROUND_HALF_UP))


def fee(gross):
    return max(MIN_FEE, int((D(gross) * FEE_RATE).quantize(D('1'), rounding=ROUND_HALF_UP)))


def positions(con, user, date):
    result = {}
    for row in con.execute('SELECT * FROM fills WHERE user_id=? ORDER BY date,rowid', (user,)):
        item = result.setdefault(row['symbol'], {'symbol': row['symbol'], 'quantity': 0, 'available': 0})
        sign = 1 if row['side'] == 'buy' else -1
        item['quantity'] += sign * row['qty']
        if row['side'] == 'sell' or row['date'] < date:
            item['available'] += sign * row['qty']
    for row in con.execute("SELECT symbol,SUM(qty) qty FROM orders WHERE user_id=? AND status='accepted' AND side='sell' GROUP BY symbol", (user,)):
        if row['symbol'] in result:
            result[row['symbol']]['available'] -= row['qty']
    return [p for p in result.values() if p['quantity']]


def account(con, user):
    a = dict(con.execute('SELECT * FROM accounts WHERE user_id=?', (user,)).fetchone())
    a['reserved'] = con.execute("SELECT COALESCE(SUM(reserved),0) FROM orders WHERE user_id=? AND status='accepted'", (user,)).fetchone()[0]
    a['available_cash'] = a['cash'] - a['reserved']
    a['positions'] = positions(con, user, a['as_of'])
    value = 0
    for p in a['positions']:
        bar = con.execute('SELECT close FROM bars WHERE user_id=? AND symbol=? AND date<=? ORDER BY date DESC LIMIT 1', (user, p['symbol'], a['as_of'])).fetchone()
        p['price'] = bar['close'] if bar else None
        p['market_value'] = money(D(bar['close']) * p['quantity']) if bar else None
        if p['market_value'] is not None:
            value += p['market_value']
    a['equity'] = a['cash'] + value
    a['pnl'] = a['equity'] - a['initial_cash']
    a['simulation'] = True
    a['fee_assumptions'] = '每笔按成交金额0.1%，最低5元，买卖同率；仅为综合成本模拟假设，非真实税费报价'
    return a


def submit(con, user, data):
    symbol, side, qty = data['symbol'], data['side'], data['quantity']
    if not symbol_ok(symbol) or side not in ('buy', 'sell'):
        fail('首版仅支持指定沪深主板代码和买卖方向')
    if type(qty) is not int or qty <= 0 or qty > 10000000:
        fail('数量必须为有效正整数')
    p = price(data['limit_price'])
    fingerprint = hashlib.sha256(json.dumps([symbol, side, qty, str(p)]).encode()).hexdigest()
    old = con.execute('SELECT * FROM orders WHERE user_id=? AND idem=?', (user, data['idempotency_key'])).fetchone()
    if old:
        if old['fingerprint'] != fingerprint:
            fail('同一幂等键不能用于不同订单')
        return dict(old)
    a = account(con, user)
    if not con.execute('SELECT 1 FROM bars WHERE user_id=? AND symbol=? AND date<=?', (user, symbol, a['as_of'])).fetchone():
        fail('当前模拟时点没有此证券的价格数据')
    reserved = 0
    if side == 'buy':
        if qty % 100:
            fail('本模拟器买入按100股整手；特殊证券不支持')
        gross = money(p * qty)
        reserved = gross + fee(gross)
        if reserved > a['available_cash']:
            fail('可用模拟资金不足')
    else:
        holding = next((x for x in a['positions'] if x['symbol'] == symbol), {'available': 0})
        if qty > holding['available']:
            fail('可卖数量不足（含T+1及委托冻结限制）')
        if qty % 100 and qty != holding['available']:
            fail('零股卖出必须一次卖出全部可卖数量')
    oid = uuid.uuid4().hex
    con.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (oid, user, data['idempotency_key'], symbol, side, qty, str(p), a['as_of'], 'accepted', reserved, '', fingerprint))
    return dict(con.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone())


def cancel(con, user, oid):
    row = con.execute('SELECT * FROM orders WHERE id=? AND user_id=?', (oid, user)).fetchone()
    if not row:
        fail('订单不存在')
    if row['status'] == 'cancelled':
        return
    if row['status'] != 'accepted':
        fail('当前状态不可撤单')
    con.execute("UPDATE orders SET status='cancelled',reserved=0 WHERE id=?", (oid,))


def advance(con, user):
    a = account(con, user)
    day = con.execute('SELECT MIN(date) FROM bars WHERE user_id=? AND date>?', (user, a['as_of'])).fetchone()[0]
    if not day:
        fail('没有后续交易日数据，请先导入日线')
    for order in con.execute("SELECT * FROM orders WHERE user_id=? AND status='accepted' ORDER BY rowid", (user,)).fetchall():
        b = con.execute('SELECT * FROM bars WHERE user_id=? AND symbol=? AND date=?', (user, order['symbol'], day)).fetchone()
        if not b:
            continue
        reason = ''
        if not b['tradable'] or b['volume'] == 0:
            reason = '停牌或数据标记不可交易'
        elif D(b['high']) == D(b['low']):
            reason = '单一价日线无法证明排队可成交，保守不成交'
        p, limit = D(b['open']), D(order['limit_price'])
        if not reason and ((order['side'] == 'buy' and p > limit) or (order['side'] == 'sell' and p < limit)):
            reason = '开盘价未满足限价；不推测盘中成交'
        if reason:
            con.execute('UPDATE orders SET reason=? WHERE id=?', (reason, order['id']))
            continue
        gross = money(p * order['qty'])
        cost = fee(gross)
        delta = -(gross + cost) if order['side'] == 'buy' else gross - cost
        if order['side'] == 'sell' and delta < 0:
            con.execute("UPDATE orders SET status='rejected',reserved=0,reason='成交金额低于模拟最低费用' WHERE id=?", (order['id'],))
            continue
        fid = uuid.uuid4().hex
        con.execute('INSERT INTO fills VALUES (?,?,?,?,?,?,?,?,?,?)', (fid, order['id'], user, order['symbol'], order['side'], order['qty'], str(p), day, gross, cost))
        con.execute('UPDATE accounts SET cash=cash+? WHERE user_id=?', (delta, user))
        balance = con.execute('SELECT cash FROM accounts WHERE user_id=?', (user,)).fetchone()[0]
        con.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?,?)', (uuid.uuid4().hex, user, day, order['side'], delta, balance, fid))
        con.execute("UPDATE orders SET status='filled',reserved=0,reason='' WHERE id=?", (order['id'],))
    con.execute('UPDATE accounts SET as_of=? WHERE user_id=?', (day, user))
    return account(con, user)
