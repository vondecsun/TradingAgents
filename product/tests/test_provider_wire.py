"""Exercise the real upstream SDK through an offline strict HTTP boundary."""
import json
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from tradingagents.llm_clients.openai_client import DeepSeekChatOpenAI, OPENAI_COMPATIBLE_PROVIDERS
from product.server.provider_compat import compatible_clients


def _client(cls,handler):
    return cls(model='deepseek-flash',api_key='test-not-real',base_url='https://api.deepseek.com',max_retries=0,
               http_client=httpx.Client(transport=httpx.MockTransport(handler)),
               http_async_client=httpx.AsyncClient(trust_env=False))


def test_real_sdk_null_content_repro_and_product_transport_fix():
    captured=[]
    def handler(request):
        body=json.loads(request.content)
        captured.append(body)
        for m in body['messages']:
            if m['role']=='assistant' and m.get('content') is None:
                return httpx.Response(400,json={'error':{'message':'assistant content must not be null','type':'invalid_request_error'}})
        return httpx.Response(200,json={'id':'probe','object':'chat.completion','created':1,'model':'deepseek-flash','choices':[{'index':0,'message':{'role':'assistant','content':'OK','reasoning_content':'synthetic reasoning'},'finish_reason':'stop'}]})
    messages=[HumanMessage('Test'),AIMessage(content='',additional_kwargs={'reasoning_content':'original reasoning'},tool_calls=[{'name':'probe','args':{},'id':'probe1','type':'tool_call'}]),ToolMessage('OK',tool_call_id='probe1')]
    from openai import BadRequestError
    with pytest.raises(BadRequestError):
        _client(DeepSeekChatOpenAI,handler).invoke(messages)
    original=OPENAI_COMPATIBLE_PROVIDERS['deepseek']
    with compatible_clients():
        cls=OPENAI_COMPATIBLE_PROVIDERS['deepseek'].chat_class
        assert _client(cls,handler).invoke(messages).content=='OK'
    assert OPENAI_COMPATIBLE_PROVIDERS['deepseek'] is original
    before,after=captured
    changed=[(i,k) for i,(a,b) in enumerate(zip(before['messages'],after['messages'])) for k in a if a[k]!=b[k]]
    assert changed==[(1,'content')]
    assert after['messages'][1]['reasoning_content']=='original reasoning'
    assert after['messages'][1]['tool_calls']==before['messages'][1]['tool_calls']


def test_400_field_hints_never_return_raw_body():
    from product.server.engine import failure_details
    class InvalidRequest(Exception):
        status_code=400
        body={'error':{'message':'Missing reasoning_content SECRET-KEY private prompt'}}
    detail=failure_details(InvalidRequest())
    assert detail['code']=='provider_reasoning_history'
    assert 'SECRET' not in json.dumps(detail)
    assert 'private prompt' not in json.dumps(detail)


def test_full_original_graph_through_real_deepseek_sdk_and_strict_http(monkeypatch,tmp_path):
    from tests.test_graph_end_to_end import offline,ARGS,STRUCTURED,TEXT,_Client
    from tradingagents.graph import trading_graph
    from tradingagents.llm_clients.factory import create_tier_client
    from product.server import native
    offline.__wrapped__(monkeypatch,tmp_path)
    monkeypatch.setenv('PRODUCT_RESEARCH_DIR',str(tmp_path/'research'))
    monkeypatch.setenv('DEEPSEEK_API_KEY','offline-fixture-key')
    seen=[]
    def handler(request):
        body=json.loads(request.content)
        seen.append(body)
        for m in body['messages']:
            assert not (m['role']=='assistant' and m.get('content') is None)
            if m.get('tool_calls'):
                assert 'reasoning_content' in m
        assert body.get('tool_choice') in (None,'auto','none')
        tools=body.get('tools',[])
        message={'role':'assistant','content':TEXT,'reasoning_content':'synthetic-fixture-only'}
        if tools:
            fn=tools[0]['function']['name']
            schemas={schema.__name__:value for schema,value in STRUCTURED.items()}
            if fn in schemas:
                message['tool_calls']=[{'id':'schema1','type':'function','function':{'name':fn,'arguments':json.dumps(schemas[fn].model_dump(mode='json'))}}]
                message['content']=''
            elif body['messages'][-1]['role']!='tool':
                message['content']=''
                message['tool_calls']=[{'id':'tool'+str(i),'type':'function','function':{'name':t['function']['name'],'arguments':json.dumps({key:value for key,value in ARGS.items() if key in t['function']['parameters'].get('properties',{})})}} for i,t in enumerate(tools)]
        return httpx.Response(200,json={'id':'fixture','object':'chat.completion','created':1,'model':'deepseek-flash','choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop'}]})
    http_client=httpx.Client(transport=httpx.MockTransport(handler))
    async_client=httpx.AsyncClient(trust_env=False)
    monkeypatch.setattr(trading_graph,'create_tier_client',lambda cfg,tier,**extra:create_tier_client(cfg,tier,http_client=http_client,http_async_client=async_client,**extra))
    settings=native.defaults()
    settings.update(llm_provider='deepseek',quick_think_llm='deepseek-flash',deep_think_llm='deepseek-flash',llm_max_retries=0)
    result=native.run({'engine':'tradingagents','_user_id':'a'*32,'_job_id':'b'*32,'research_settings':settings,'symbol':'000001.SZ','as_of':'2026-01-09'})
    assert result['full_core_output']
    assert len(result['coverage'])==12
    assert result['rating']=='Overweight'
    assert len(seen)>12
    assert any(any(m.get('role')=='tool' for m in body['messages']) for body in seen)
    assert result['source_integrity']['unchanged']


def test_model_check_uses_original_sdk_for_both_tiers(monkeypatch,tmp_path):
    from product.server import native
    from tradingagents.llm_clients import factory
    original_factory=factory.create_tier_client
    bodies=[]
    def handler(request):
        body=json.loads(request.content)
        bodies.append(body)
        message={'role':'assistant','content':'OK','reasoning_content':'offline reason'}
        tools=body.get('tools',[])
        if tools:
            name=tools[0]['function']['name']
            if name=='ProbeResult' or body['messages'][-1]['role']!='tool':
                message['content']=''
                message['tool_calls']=[{'id':'probe1','type':'function','function':{'name':name,'arguments':json.dumps({'status':'OK'} if name=='ProbeResult' else {})}}]
        for m in body['messages']:
            if m['role']=='assistant':assert m['content'] is not None
        return httpx.Response(200,json={'id':'probe','object':'chat.completion','created':1,'model':'deepseek-flash','choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if 'tool_calls' in message else 'stop'}]})
    sync=httpx.Client(transport=httpx.MockTransport(handler))
    asynchronous=httpx.AsyncClient(trust_env=False)
    monkeypatch.setattr(factory,'create_tier_client',lambda cfg,tier:original_factory(cfg,tier,http_client=sync,http_async_client=asynchronous))
    monkeypatch.setenv('DEEPSEEK_API_KEY','offline-key')
    monkeypatch.setenv('PRODUCT_RESEARCH_DIR',str(tmp_path))
    settings=native.defaults()
    settings.update(llm_provider='deepseek',quick_think_llm='deepseek-flash',deep_think_llm='deepseek-flash')
    result=native.run({'engine':'model_check','_user_id':'c'*32,'_job_id':'d'*32,'research_settings':settings,'as_of':'2026-01-09'})
    assert result['live_verified'] and len(result['sections'])==2
    assert len(bodies)==8
    assert result['mode']=='model_check'
    assert 'offline reason' not in json.dumps(result)
