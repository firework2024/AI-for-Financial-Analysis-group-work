from finagent.auth.user_settings import UserAPISettings, resolve_chat_agent_options


def test_resolve_chat_agent_options_user_override():
    settings = UserAPISettings(chat_max_steps=6, chat_agent_mode="single")
    opts = resolve_chat_agent_options(settings)
    assert opts["chat_max_steps"] == 6
    assert opts["chat_agent_mode"] == "single"
