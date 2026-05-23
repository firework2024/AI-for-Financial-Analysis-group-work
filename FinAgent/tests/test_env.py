from finagent import env


def test_load_dotenv_from_project_root(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        """
        # comment
        OPENAI_API_KEY='from_env'
        OPENAI_MODEL=mini
        OPENAI_BASE_URL=https://example.com
        EXISTING=value_from_dotenv
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(env, "project_root", lambda: tmp_path)
    monkeypatch.setenv("EXISTING", "system_value")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    env.load_dotenv.cache_clear()

    env.load_dotenv()

    assert env.get_env("OPENAI_API_KEY") == "from_env"
    assert env.get_env("OPENAI_MODEL") == "mini"
    assert env.get_env("OPENAI_BASE_URL") == "https://example.com"
    assert env.get_env("EXISTING") == "system_value"
