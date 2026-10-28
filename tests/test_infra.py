from writing_flow import config, paths, phase


def test_env_prefers_new_name(monkeypatch):
    monkeypatch.setenv("HARNESS_KIT_STE", "strict")
    monkeypatch.setenv("WRITING_FLOW_STE", "off")
    assert config.env("STE") == "off"


def test_env_falls_back_to_legacy_name(monkeypatch):
    monkeypatch.setenv("HARNESS_KIT_STE", "strict")
    assert config.env("STE") == "strict"


def test_corrupt_config_gives_defaults(tmp_path, monkeypatch):
    bad = tmp_path / "config.json"
    bad.write_text("{not json")
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(bad))
    assert config.hook_config("guard_style") == {}
    assert config.hook_enabled("guard_style") is True
    assert config.hook_verbosity("guard_style") == "auto"
    assert config.retro_fix_enabled() is True


def test_hook_disabled_by_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"hooks": {"guard_flow": {"enabled": false}}}')
    monkeypatch.setenv("WRITING_FLOW_CONFIG", str(cfg))
    assert config.hook_enabled("guard_flow") is False


def test_bypass_marker_releases_bypassable_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert config.bypass_release("guard_style", "x [writing-flow-bypass]") is not None
    assert config.bypass_release("guard_style", "x [kit-bypass]") is not None


def test_bypass_ignored_for_other_hooks():
    assert config.bypass_release("style_check", "x [writing-flow-bypass]") is None


def test_state_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WRITING_FLOW_STATE_DIR", str(tmp_path))
    assert paths.state_dir() == tmp_path


def test_unknown_phase_is_empty(tmp_path):
    assert phase.read_current_phase(tmp_path, "nosuchsession") == {}
