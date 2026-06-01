from finagent.chat.data_tools import build_chat_context_blob, resolve_stocks_for_chat
from finagent.chat.store import ChatMessage, ChatSession


def _session_with_dialogue() -> ChatSession:
    session = ChatSession(
        id="s-dialogue",
        title="对比",
        created_at="",
        updated_at="",
    )
    session.messages = [
        ChatMessage(role="user", content="介绍一下寒武纪和宁德时代", created_at=""),
        ChatMessage(
            role="assistant",
            content="寒武纪(688256)专注 AI 芯片，宁德时代(300750)是动力电池龙头。",
            created_at="",
        ),
    ]
    return session


def test_build_chat_context_includes_assistant():
    session = _session_with_dialogue()
    blob = build_chat_context_blob(session, "他们的 PE")
    assert "688256" in blob
    assert "300750" in blob
    assert "寒武纪" in blob


def test_resolve_stocks_from_assistant_history():
    session = _session_with_dialogue()
    assert sorted(resolve_stocks_for_chat("他们的 PE", session)) == ["300750", "688256"]


def test_resolve_stocks_name_only_in_assistant():
    session = ChatSession(id="s2", title="", created_at="", updated_at="")
    session.messages = [
        ChatMessage(role="user", content="说说茅台", created_at=""),
        ChatMessage(
            role="assistant",
            content="贵州茅台近年营收稳健，股息率有所提升。",
            created_at="",
        ),
    ]
    assert resolve_stocks_for_chat("净利润多少", session) == ["600519"]
