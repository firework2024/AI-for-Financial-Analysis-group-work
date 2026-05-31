import pytest

from finagent.chat.data_tools import resolve_stock_for_chat, resolve_stock_from_message
from finagent.chat.stock_bind import message_requests_data_ingest, should_run_chat_bootstrap
from finagent.chat.store import ChatSession


def test_resolve_alias_from_message():
    assert resolve_stock_from_message("比亚迪最近股价") == "002594"
    assert resolve_stock_from_message("分析一下宁德时代") == "300750"


def test_resolve_code_in_message():
    assert resolve_stock_from_message("300274 今天收盘多少") == "300274"


def test_resolve_prefers_message_over_session():
    session = ChatSession(
        id="s1",
        title="t",
        created_at="",
        updated_at="",
        stock_code="600519",
    )
    assert resolve_stock_for_chat("比亚迪营收怎么样", session) == "002594"


def test_message_requests_ingest():
    assert message_requests_data_ingest("帮我把比亚迪数据入库") is True
    assert message_requests_data_ingest("最近股价") is False


def test_should_bootstrap_when_stock_mentioned_and_missing(monkeypatch):
    monkeypatch.setenv("FINAGENT_AUTO_INGEST_ON_NEW_CHAT", "true")
    session = ChatSession(id="s1", title="新对话", created_at="", updated_at="")
    assert should_run_chat_bootstrap(session, "002594", "看看比亚迪") is True
