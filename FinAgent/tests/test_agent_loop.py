from finagent.chat.agent_loop import _execute_tool, chat_agent_max_steps, chat_agent_mode
from finagent.chat.store import ChatSession


def test_chat_agent_mode_default_loop():
    assert chat_agent_mode() in {"loop", "single"}


def test_chat_agent_max_steps_bounds():
    assert 1 <= chat_agent_max_steps() <= 8


def test_execute_get_session():
    session = ChatSession(
        id="s1",
        title="t",
        created_at="",
        updated_at="",
        stock_code="688256",
        stock_codes=["688256", "300750"],
    )
    out = _execute_tool("get_session", {}, session, "他们的pe")
    assert out["stock_codes"] == ["688256", "300750"]
