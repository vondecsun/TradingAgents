"""Run DOM flows against an isolated temporary database; never touch user data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]

def main():
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory() as folder:
        env={**os.environ,'PRODUCT_DB':folder+'/db.sqlite3','PRODUCT_TEST_BILLING':'true','PRODUCT_OPEN_BROWSER':'false','PRODUCT_HOST':'127.0.0.1','PRODUCT_PORT':'18765','PRODUCT_TEST_URL':'http://127.0.0.1:18765'}
        server=subprocess.Popen([sys.executable,'product/launch.py'],env=env)
        try:
            ready=False
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Temporary test server failed to start')
                try:
                    urllib.request.urlopen(env['PRODUCT_TEST_URL']+'/api/v1/health',timeout=1)
                    ready=True
                    break
                except OSError:
                    time.sleep(.1)
            if not ready:
                raise RuntimeError('Temporary test server timed out')
            result=subprocess.run(['node','product/tests/frontend-smoke.cjs'],env=env)
            return result.returncode
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill();server.wait()

if __name__=='__main__':
    raise SystemExit(main())
