from pvb.extraction.openrouter.settings import OpenRouterSettings
from pvb.extraction.pipeline import main


def test_openrouter_help_dispatch(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["--backend", "openrouter", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    assert "--confirm-paid-run" in text and "--confirm-full-run" in text


def test_config_check_never_uses_network(monkeypatch, capsys):
    import httpx

    monkeypatch.setattr("pvb.extraction.openrouter.cli.load_settings", lambda: OpenRouterSettings())
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    assert main(["--backend", "openrouter", "--mode", "config-check"]) == 1
    assert "API key is not configured" in capsys.readouterr().out


def test_preflight_without_model_never_uses_network(monkeypatch, capsys):
    import httpx

    monkeypatch.setattr("pvb.extraction.openrouter.cli.load_settings", lambda: OpenRouterSettings())
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    assert main(["--backend=openrouter", "--mode", "preflight"]) == 1
    assert "exact OPENROUTER_MODEL" in capsys.readouterr().out
