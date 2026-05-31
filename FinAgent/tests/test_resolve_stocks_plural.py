from finagent.chat.data_tools import resolve_stocks_for_chat
from finagent.chat.store import ChatSession


def test_plural_ref_uses_session_stock_codes():
    session = ChatSession(
        id="s1",
        title="对比",
        created_at="",
        updated_at="",
        stock_code="688256",
        stock_codes=["688256", "300750", "600519"],
    )
    assert resolve_stocks_for_chat("他们的pe", session) == ["688256", "300750", "600519"]
    assert resolve_stocks_for_chat("这几个公司的PE", session) == ["688256", "300750", "600519"]
