import json

import pytest
from pydantic import SecretStr

from pvb.extraction.openrouter.settings import ConfigurationError, OpenRouterSettings, load_settings


def test_dotenv_load_without_export(tmp_path):
    secret = "sk-or-unit-test-credential"
    path = tmp_path / ".env"
    path.write_text(
        "OPENROUTER_API_KEY=" + secret + "\nOPENROUTER_MODEL=fixture/model\nPVB_API_CONCURRENCY=2\n"
    )
    settings = load_settings(tmp_path, environ={})
    settings.require_ready()
    assert settings.concurrency == 2 and settings.model == "fixture/model"
    assert secret not in repr(settings) and secret not in settings.model_dump_json()
    assert secret not in json.dumps(settings.public())
    assert settings.redact("Bearer " + secret) == "Bearer [REDACTED]"
    assert path.read_text().startswith("OPENROUTER_API_KEY=" + secret)


def test_environment_precedence_and_no_interpolation(tmp_path):
    (tmp_path / ".env").write_text(
        "OPENROUTER_MODEL=fixture/file\nOPENROUTER_API_KEY=${DO_NOT_INTERPOLATE}\n"
    )
    settings = load_settings(tmp_path, environ={"OPENROUTER_MODEL": "fixture/environment"})
    assert settings.model == "fixture/environment"
    assert settings.credential.get_secret_value() == "${DO_NOT_INTERPOLATE}"


@pytest.mark.parametrize(
    "credential", ["", "PASTE_YOUR_API_KEY_HERE", "your_actual_api_key", "<key>", "placeholder"]
)
def test_missing_or_placeholder_key(credential):
    settings = OpenRouterSettings(credential=SecretStr(credential), model="fixture/model")
    with pytest.raises(ConfigurationError, match="API key is not configured"):
        settings.require_ready()


@pytest.mark.parametrize(
    "model", ["", "openrouter/auto", "plain-name", "test/model?key=secret", "test/../secret"]
)
def test_invalid_model(model):
    settings = OpenRouterSettings(credential=SecretStr("fixture-secret"), model=model)
    with pytest.raises(ConfigurationError, match="OPENROUTER_MODEL"):
        settings.require_ready()


def test_endpoint_change_refused():
    settings = OpenRouterSettings(
        credential=SecretStr("fixture-secret"),
        model="fixture/model",
        base_url="https://attacker.invalid/api",
    )
    with pytest.raises(ConfigurationError, match="BASE_URL"):
        settings.require_ready()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PVB_API_CONCURRENCY", "0"),
        ("PVB_API_MAX_RETRIES", "-1"),
        ("PVB_API_TIMEOUT_SECONDS", "nan"),
        ("PVB_API_MAX_COST_USD", "-1"),
        ("PVB_CLASSIFICATION_MAX_OUTPUT_TOKENS", "0"),
        ("PVB_CLASSIFICATION_TEMPERATURE", "nan"),
    ],
)
def test_invalid_env_values_not_echoed(tmp_path, key, value):
    (tmp_path / ".env").write_text(f"{key}={value}\n")
    with pytest.raises(ConfigurationError) as exc:
        load_settings(tmp_path, environ={})
    assert "input_value" not in str(exc.value)
    assert f"={value}" not in str(exc.value)


def test_credentials_not_in_public_field(tmp_path):
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=fixture-secret\nOPENROUTER_MODEL=fixture/fixture-secret\n"
    )
    with pytest.raises(ConfigurationError, match="non-secret"):
        load_settings(tmp_path, environ={})
