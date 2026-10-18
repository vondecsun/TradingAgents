"""Product API transport compatibility; never changes agents, prompts or decisions."""
from contextlib import contextmanager
from dataclasses import replace


@contextmanager
def compatible_clients():
    from tradingagents.llm_clients.openai_client import (
        OPENAI_COMPATIBLE_PROVIDERS, DeepSeekChatOpenAI,
    )

    class DeepSeekWireClient(DeepSeekChatOpenAI):
        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            # LangChain converts empty assistant content into null for tool calls.
            # DeepSeek integrations require non-null assistant content on replay.
            # Preserve every original tool call and reasoning_content verbatim.
            for message in payload.get('messages', []):
                if message.get('role') == 'assistant' and message.get('content') is None:
                    message['content'] = ''
            return payload

    original = OPENAI_COMPATIBLE_PROVIDERS['deepseek']
    OPENAI_COMPATIBLE_PROVIDERS['deepseek'] = replace(original, chat_class=DeepSeekWireClient)
    try:
        yield
    finally:
        OPENAI_COMPATIBLE_PROVIDERS['deepseek'] = original
