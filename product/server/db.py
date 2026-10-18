"""Single-host persistence; keep the database outside the web root."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS watchlist(user_id TEXT NOT NULL,symbol TEXT NOT NULL,PRIMARY KEY(user_id,symbol));
CREATE TABLE IF NOT EXISTS bars(user_id TEXT NOT NULL,symbol TEXT NOT NULL,date TEXT NOT NULL,open TEXT NOT NULL,high TEXT NOT NULL,low TEXT NOT NULL,close TEXT NOT NULL,volume INTEGER NOT NULL,source TEXT NOT NULL,mode TEXT NOT NULL,tradable INTEGER NOT NULL,PRIMARY KEY(user_id,symbol,date));
CREATE TABLE IF NOT EXISTS market_bars(user_id TEXT NOT NULL,symbol TEXT NOT NULL,date TEXT NOT NULL,open TEXT NOT NULL,high TEXT NOT NULL,low TEXT NOT NULL,close TEXT NOT NULL,volume INTEGER NOT NULL,source TEXT NOT NULL,mode TEXT NOT NULL,tradable INTEGER NOT NULL,PRIMARY KEY(user_id,symbol,date));
CREATE TABLE IF NOT EXISTS market_fetches(user_id TEXT NOT NULL,symbol TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,fetched INTEGER NOT NULL,name TEXT NOT NULL,PRIMARY KEY(user_id,symbol,start,end));
CREATE TABLE IF NOT EXISTS accounts(user_id TEXT PRIMARY KEY,cash INTEGER NOT NULL,as_of TEXT NOT NULL,initial_cash INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,idem TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL,limit_price TEXT NOT NULL,created_date TEXT NOT NULL,status TEXT NOT NULL,reserved INTEGER NOT NULL,reason TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL,UNIQUE(user_id,idem));
CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL,user_id TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL,price TEXT NOT NULL,date TEXT NOT NULL,gross INTEGER NOT NULL,fee INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,date TEXT NOT NULL,kind TEXT NOT NULL,amount INTEGER NOT NULL,balance INTEGER NOT NULL,reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(user_id TEXT PRIMARY KEY,plan TEXT NOT NULL,expires INTEGER NOT NULL,mode TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,idem TEXT NOT NULL,symbol TEXT NOT NULL,engine TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,error TEXT,report TEXT,period TEXT NOT NULL,cost INTEGER NOT NULL,cancel INTEGER NOT NULL DEFAULT 0,input TEXT NOT NULL,UNIQUE(user_id,idem));
CREATE TABLE IF NOT EXISTS research_settings(user_id TEXT PRIMARY KEY,config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS billing_orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,plan TEXT NOT NULL,amount INTEGER NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS billing_events(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status,created);
CREATE INDEX IF NOT EXISTS idx_fills_user ON fills(user_id,date);
'''


def connect():
    path = Path(os.environ.get('PRODUCT_DB', 'product-data/product.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=20000')
    return con


@contextmanager
def transaction():
    con = connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        yield con
        if con.in_transaction:
            con.commit()
    except BaseException:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def init():
    con = connect()
    try:
        con.executescript(SCHEMA)
        con.execute('PRAGMA journal_mode=WAL')
    finally:
        con.close()
