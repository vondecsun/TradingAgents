from pathlib import Path
import ssl
import certifi
import pytest
from product import tls_setup


def test_unicode_ca_copy_preserves_trust_bytes_and_env(monkeypatch,tmp_path):
    folder=tmp_path/'中文目录'
    folder.mkdir()
    source=folder/'original.pem'
    source.write_bytes(Path(certifi.where()).read_bytes())
    monkeypatch.setattr(tls_setup,'WINDOWS',True)
    for name in tls_setup._CA_VARS:monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('CURL_CA_BUNDLE',str(source))
    tls_setup.configure_tls()
    target=Path(__import__('os').environ['CURL_CA_BUNDLE'])
    assert str(target).isascii() and target!=source
    assert target.read_bytes()==source.read_bytes()
    ssl.create_default_context(cafile=str(target))
    assert 'SSL_CERT_FILE' not in __import__('os').environ


def test_invalid_explicit_ca_is_not_silently_replaced(monkeypatch,tmp_path):
    monkeypatch.setattr(tls_setup,'WINDOWS',True)
    monkeypatch.setenv('SSL_CERT_FILE',str(tmp_path/'missing.pem'))
    with pytest.raises(ValueError,match='未关闭证书校验'):
        tls_setup.configure_tls()
