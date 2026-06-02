from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "finagent" / "web" / "static" / "chat.js"
INDEX_HTML = ROOT / "finagent" / "web" / "static" / "index.html"


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    params_end = source.index(")", start)
    brace = source.index("{", params_end)
    depth = 0
    for pos in range(brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : pos]
    raise AssertionError(f"function body not found: {name}")


def test_bootstrap_modal_sync_does_not_reenter_header_update():
    source = CHAT_JS.read_text(encoding="utf-8")
    body = _function_body(source, "syncBootstrapModal")
    assert "updateChatHeader(" not in body


def test_bootstrap_polling_is_deduplicated_per_session():
    source = CHAT_JS.read_text(encoding="utf-8")
    body = _function_body(source, "pollSessionBootstrap")
    assert "chatState.bootstrapPolls.has(sessionId)" in body
    assert "chatState.bootstrapPolls.set(sessionId" in body
    assert "chatState.bootstrapPolls.delete(sessionId)" in body


def test_new_chat_preserves_sidebar_stock_in_payload():
    source = CHAT_JS.read_text(encoding="utf-8")
    body = _function_body(source, "createChatSession")
    payload_pos = body.index("const stocksPayload = chatStocksPayload()")
    reset_pos = body.index('chatEls.chatStockInput.value = ""')
    assert payload_pos < reset_pos
    assert "hadSidebarStock" in body
    assert "clearStockInput: resetStockInput && !hadSidebarStock" in body


def test_ready_status_requires_per_stock_detail():
    source = CHAT_JS.read_text(encoding="utf-8")
    body = _function_body(source, "buildDataStatusContext")
    completed_pos = body.index('boot?.status === "completed"')
    ready_pos = body.index("基础数据就绪")
    assert "summary.allReady" in body[completed_pos:ready_pos]
    assert "入库状态待确认" in body
    assert "部分就绪" in body


def test_index_uses_latest_chat_cache_buster():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "/assets/chat.js?v=20260602coveragefix" in html
    assert 'id="chatSyncDataBtn"' in html


def test_chat_has_sync_data_handler():
    source = CHAT_JS.read_text(encoding="utf-8")
    assert "syncSessionData" in source
    assert "chatSyncDataBtn" in source
    assert "/api/chat/sessions/" in source
    assert "/bootstrap" in source
