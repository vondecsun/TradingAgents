"""Runs from any working directory. Defaults to loopback, never the public network."""
import os
from pathlib import Path
import sys
import threading
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
# Minimal dotenv reader; no shell evaluation or dependency on the research engine.
config = ROOT/'product'/'.env'
if config.exists():
    for line in config.read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            k,v=line.split('=',1)
            os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
if __name__ == '__main__':
    import uvicorn
    host = os.getenv('PRODUCT_HOST','127.0.0.1')
    port = int(os.getenv('PRODUCT_PORT','8765'))
    if host in ('127.0.0.1','localhost') and os.getenv('PRODUCT_OPEN_BROWSER','true')=='true':
        threading.Timer(1.5,lambda:webbrowser.open(f'http://127.0.0.1:{port}')).start()
    uvicorn.run('product.server.app:app',host=host,port=port,workers=1,access_log=False)
