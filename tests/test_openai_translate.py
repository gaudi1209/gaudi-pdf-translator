import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.openai_translate import OpenAITranslateService


def test_init_default():
    svc = OpenAITranslateService(api_key="test-key")
    assert svc.model == "gpt-4o-mini"
    assert svc.base_url == "https://api.openai.com/v1"


def test_init_custom():
    svc = OpenAITranslateService(
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test"
    )
    assert svc.model == "deepseek-chat"
    assert svc.base_url == "https://api.deepseek.com/v1"


def test_build_messages():
    svc = OpenAITranslateService(api_key="test")
    msgs = svc._build_messages("Hello world")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Chinese" in msgs[0]["content"]
    assert msgs[1]["content"] == "Hello world"
