import sys
import types

from y_agents_plugins.llm import langchain as lc


def _config(**kw):
    base = {
        "model": "m",
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key": None,
        "temperature": None,
        "max_tokens": None,
    }
    base.update(kw)
    return lc.LangChainLLMConfig(**base)




def test_a_plain_http_endpoint_with_an_ollama_tag_is_still_ollama():
    assert lc._looks_like_ollama(_config(model="llama3:8b"))


def test_an_authenticated_ollama_endpoint_gets_the_bearer_token(monkeypatch):
    seen = {}

    class FakeChatOllama:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    fake = types.ModuleType("langchain_ollama")
    fake.ChatOllama = FakeChatOllama
    monkeypatch.setitem(sys.modules, "langchain_ollama", fake)
    client = lc.LangChainTextGenerator(_config(base_url="https://ollama.com/v1", api_key="sk-secret"))
    client._build_chat_model()
    assert seen["client_kwargs"] == {"headers": {"Authorization": "Bearer sk-secret"}}
    assert seen["base_url"] == "https://ollama.com"
