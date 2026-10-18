import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from .db import transaction
from . import native


def now():
    return datetime.now(timezone.utc).isoformat()


def recover():
    with transaction() as con:
        # This build deliberately supports exactly one API process / worker.
        # Interrupted model calls are failed, never silently repeated and billed twice.
        con.execute("UPDATE jobs SET status='failed',stage='服务重启，任务中断；额度已释放',error='interrupted',cost=0,updated=? WHERE status='running'", (now(),))


def work(stop):
    while not stop.wait(0.3):
        with transaction() as con:
            job = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not job:
                continue
            job = dict(job)
            con.execute("UPDATE jobs SET status='running',stage='核对数据并生成报告',updated=? WHERE id=?", (now(), job['id']))
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-m', 'product.server.engine'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            budget = int(os.getenv('PRODUCT_BACKTEST_TIMEOUT','7200')) if job['engine']=='backtest' else int(os.getenv('PRODUCT_RESEARCH_TIMEOUT','1800')) if job['engine'] in native.NATIVE_ENGINES else int(os.getenv('PRODUCT_JOB_TIMEOUT','300'))
            deadline = time.monotonic() + budget
            data=json.loads(job['input'])
            if job['engine'] in native.NATIVE_ENGINES:
                data.update(_user_id=job['user_id'],_job_id=job['id'])
            payload = json.dumps(data,ensure_ascii=False)
            while True:
                try:
                    stdout, _ = process.communicate(input=payload, timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
                    if job['engine'] in native.NATIVE_ENGINES:
                        path=native.progress_path(job['user_id'],job['id'])
                        try:
                            progress=json.loads(path.read_text(encoding='utf-8'))
                            with transaction() as con:
                                con.execute("UPDATE jobs SET stage=?,updated=? WHERE id=? AND cancel=0",(progress.get('stage','原生代理运行中')[:200],now(),job['id']))
                        except (OSError,ValueError):
                            pass
                    with transaction() as con:
                        cancelled = con.execute('SELECT cancel FROM jobs WHERE id=?', (job['id'],)).fetchone()[0]
                    if cancelled or stop.is_set() or time.monotonic() > deadline:
                        process.kill()
                        process.communicate()
                        raise InterruptedError('cancelled' if cancelled or stop.is_set() else 'timeout')
            if process.returncode:
                raise RuntimeError('engine_failed')
            report = json.loads(stdout)
            with transaction() as con:
                cancelled = con.execute('SELECT cancel FROM jobs WHERE id=?', (job['id'],)).fetchone()[0]
                if cancelled:
                    con.execute("UPDATE jobs SET status='cancelled',cost=0,stage='已取消',updated=? WHERE id=?", (now(), job['id']))
                else:
                    con.execute("UPDATE jobs SET status='completed',stage='报告已完成',report=?,updated=? WHERE id=?", (json.dumps(report, ensure_ascii=False), now(), job['id']))
        except Exception as exc:
            if process and process.poll() is None:
                process.kill()
                process.communicate()
            code = str(exc) if isinstance(exc, InterruptedError) else 'engine_failed'
            status = 'cancelled' if code == 'cancelled' else 'failed'
            with transaction() as con:
                con.execute('UPDATE jobs SET status=?,stage=?,error=?,cost=0,updated=? WHERE id=?', (status, ('原生任务中断，已保留检查点；可手动恢复' if job['engine'] in native.NATIVE_ENGINES else '任务中断，额度已释放；请检查引擎配置') if status == 'failed' else '已取消', code, now(), job['id']))
