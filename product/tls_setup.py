"""Preserve CA verification when Windows curl cannot read Unicode bundle paths."""
import os
from pathlib import Path
import ssl
import tempfile

WINDOWS = os.name == 'nt'
_BUNDLES = {}
_DIRECTORIES = []
_CA_VARS = ('SSL_CERT_FILE', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE')


def _ascii_bundle(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('配置的HTTPS证书文件不存在；未关闭证书校验')
    if str(source).isascii():
        return str(source)
    if str(source) in _BUNDLES:
        return _BUNDLES[str(source)]
    # Validate the original bundle with Python's Unicode-aware file handling.
    ssl.create_default_context(cafile=str(source))
    parents = [tempfile.gettempdir(), os.getenv('LOCALAPPDATA', '')]
    parent = next((p for p in parents if p and str(Path(p).resolve()).isascii() and Path(p).is_dir()), None)
    if parent is None:
        raise ValueError('未找到英文临时目录，无法为行情库加载HTTPS证书；未关闭证书校验')
    folder = tempfile.TemporaryDirectory(prefix='hengyan-ca-', dir=parent)
    destination = Path(folder.name) / 'cacert.pem'
    try:
        destination.write_bytes(source.read_bytes())
        if os.name != 'nt':
            destination.chmod(0o600)
    except BaseException:
        folder.cleanup()
        raise
    _DIRECTORIES.append(folder)
    _BUNDLES[str(source)] = str(destination)
    return str(destination)


def configure_tls():
    """Call before curl_cffi/yfinance import; copy trust material, never disable it."""
    if not WINDOWS:
        return
    explicit = {name: os.environ[name] for name in _CA_VARS if os.environ.get(name)}
    if explicit:
        for name, source in explicit.items():
            os.environ[name] = _ascii_bundle(source)
        return
    import certifi
    source = ssl.get_default_verify_paths().cafile or certifi.where()
    resolved = _ascii_bundle(source)
    if resolved != str(Path(source).resolve()):
        for name in _CA_VARS:
            os.environ[name] = resolved
