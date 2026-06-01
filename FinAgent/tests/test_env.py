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


def test_load_dotenv_skips_empty_values(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        """
        RQDATAC2_CONF=
        RQ_USER=
        REAL_KEY=hello
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(env, "project_root", lambda: tmp_path)
    monkeypatch.delenv("RQDATAC2_CONF", raising=False)
    monkeypatch.delenv("RQ_USER", raising=False)
    monkeypatch.delenv("REAL_KEY", raising=False)
    env.load_dotenv.cache_clear()

    env.load_dotenv()

    assert "RQDATAC2_CONF" not in __import__("os").environ or env.get_env("RQDATAC2_CONF") is None
    assert env.get_env("REAL_KEY") == "hello"


def test_prepare_rqdata_env_reads_conf_file(monkeypatch, tmp_path):
    conf = tmp_path / "rq.conf"
    conf.write_text("tcp://license:token@rqdatad-pro.ricequant.com:16011", encoding="utf-8")
    monkeypatch.setattr(env, "project_root", lambda: tmp_path)
    monkeypatch.setenv("RQDATAC2_CONF_FILE", str(conf))
    monkeypatch.delenv("RQDATAC2_CONF", raising=False)
    env.load_dotenv.cache_clear()

    env.prepare_rqdata_env()

    assert env.get_env("RQDATAC2_CONF") == "tcp://license:token@rqdatad-pro.ricequant.com:16011"


def test_rqdata_configured_with_env_uri(monkeypatch):
    monkeypatch.setenv("RQDATAC2_CONF", "tcp://license:token@host:16011")
    env.load_dotenv.cache_clear()
    assert env.rqdata_configured() is True
