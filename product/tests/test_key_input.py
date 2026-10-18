from product import key_input


def test_key_format_rejects_single_control_character_without_disclosing_key():
    for value in ('', 'x', '\x16', 'short', 'sk-abc defghijk', 'sk-abc\x16defghijk', 'Bearer sk-test-test', '中文apikey123456'):
        assert key_input.credential_error(value)
    assert key_input.credential_error('sk-test-not-a-real-api-key') is None


def test_console_reprompts_after_failed_paste(monkeypatch,capsys):
    monkeypatch.setattr(key_input,'WINDOWS',False)
    replies=iter(['\x16','sk-test-not-a-real-api-key'])
    monkeypatch.setattr(key_input,'getpass',lambda prompt:next(replies))
    assert key_input.read_api_key('key')=='sk-test-not-a-real-api-key'
    output=capsys.readouterr().out
    assert 'sk-test' not in output and '\x16' not in output


def test_windows_dialog_and_optional_local_key(monkeypatch):
    monkeypatch.setattr(key_input,'WINDOWS',True)
    monkeypatch.setattr(key_input,'_windows_secret',lambda prompt:' sk-test-not-a-real-api-key ')
    assert key_input.read_api_key('key')=='sk-test-not-a-real-api-key'
    monkeypatch.setattr(key_input,'_windows_secret',lambda prompt:'')
    assert key_input.read_api_key('key',optional=True)==''


def test_capability_never_accepts_single_character_key(monkeypatch):
    from product.server import native
    monkeypatch.setenv('DEEPSEEK_API_KEY','\x16')
    settings=native.defaults()
    settings.update(llm_provider='deepseek')
    cap=native.capability(settings)
    assert not cap['configured']
    assert all(not x['configured'] and x['credential_error'] for x in cap['tiers'])
