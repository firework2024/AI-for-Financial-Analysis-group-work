from finagent.chat.answer_format import sanitize_chat_answer


def test_sanitize_chat_answer_strips_moving_average_figure_block():
    raw = (
        "结论如下。\n\n"
        "#### 图 · 收盘价与 MA20/MA60\n\n"
        "![收盘价与 MA20/MA60](charts/300750/moving_averages.png)\n\n"
        "**图注** 均线整理。\n\n"
        "MA20 约 320 点。"
    )
    out = sanitize_chat_answer(raw)
    assert "#### 图 ·" not in out
    assert "moving_averages" not in out
    assert "MA20 约 320" in out


def test_sanitize_chat_answer_keeps_other_content():
    text = "最新收盘 10.5 元，20 日涨跌 -2%。"
    assert sanitize_chat_answer(text) == text
