import json

import pytest

from pvb.ingestion.adapters.strongreject import adapt
from pvb.schemas.annotations import SampleAnnotation
from pvb.translation.__main__ import prepare
from pvb.translation.settings import TranslationSettings, load_settings


def test_translation_settings_reuse_named_key_without_exposing_it(tmp_path):
    secret = "private-gap-translation-fixture"
    google = "private-google-translation-fixture"
    (tmp_path / ".env").write_text(
        "GAPGPT_API_KEY=" + secret + "\nGOOGLE_TRANSLATE_API_KEY=" + google + "\n"
        "PVB_TRANSLATION_SCOPE=all\nPVB_TRANSLATION_LLM_MODEL=gpt-5.6-terra\n"
    )
    settings = load_settings(tmp_path, environ={})
    assert not any(settings.issues().values())
    assert settings.llm_credential.get_secret_value() == secret
    public = json.dumps(settings.public()) + repr(settings)
    assert secret not in public and google not in public
    assert settings.scope == "all" and settings.google_model == "nmt"


def test_google_placeholder_reports_exact_missing_field(tmp_path):
    (tmp_path / ".env").write_text("GOOGLE_TRANSLATE_API_KEY=PASTE_YOUR_KEY_HERE\n")
    settings = load_settings(tmp_path, environ={})
    assert "GOOGLE_TRANSLATE_API_KEY" in " ".join(settings.issues()["google_translate"])


def test_translation_provider_and_credential_must_match():
    settings = TranslationSettings(llm_provider="openrouter")
    assert any("must match" in issue for issue in settings.issues()["llm"])


def test_secret_accidentally_used_as_model_is_rejected(tmp_path):
    secret = "private-credential-fixture"
    (tmp_path / ".env").write_text(
        "GAPGPT_API_KEY=" + secret + "\nPVB_TRANSLATION_LLM_MODEL=" + secret + "\n"
    )
    with pytest.raises(ValueError) as exc:
        load_settings(tmp_path, environ={})
    assert secret not in str(exc.value)


def test_language_plans_preserve_groups_ids_and_never_invent_translations(
    tmp_path, synthetic_sample, decision_data, run
):
    samples = [
        synthetic_sample("Original English.", context="Exact context.\n"),
        adapt(
            {
                "category": "Violence",
                "source": "custom",
                "forbidden_prompt": "Another original English request.",
            }
        ),
    ]
    rows = []
    for i, sample in enumerate(samples):
        label = "unsafe_violence" if i == 0 else "out_of_scope"
        annotation = SampleAnnotation(
            **{
                **decision_data,
                "label": label,
                "subcategories": ["V3"] if i == 0 else [],
                "intent": "harmful" if i == 0 else "benign",
            },
            annotation_id="fixture-annotation-" + str(i),
            sample_id=sample.sample_id,
            review_status="pending",
            annotation_method="llm",
            annotator_id="fixture-model",
            annotation_run_id=run.run_id,
            created_at=run.started_at,
            updated_at=run.started_at,
        )
        rows.append(
            {
                **sample.model_dump(mode="json"),
                "classification_label": label,
                "category": "unsafe_violence" if i == 0 else "other_violence",
                "annotation": annotation.model_dump(mode="json"),
            }
        )
    (tmp_path / "source.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    settings = TranslationSettings(input="source.jsonl", output="variants")
    report = prepare(settings, tmp_path)
    assert report["category_counts"] == {"unsafe_violence": 1, "other_violence": 1}
    assert (
        report["paid_requests"] == report["network_requests"] == report["translated_samples"] == 0
    )
    from pathlib import Path

    directory = Path(report["plan_directory"])
    english = [
        json.loads(s) for s in (directory / "english/samples.jsonl").read_text().splitlines()
    ]
    assert [r["prompt"] for r in english] == [s.original_prompt for s in samples]
    assert english[0]["context"] == samples[0].original_context
    for name, provider in [
        ("llm_translation", "gapgpt"),
        ("google_translate", "google_cloud_translation"),
    ]:
        pending = [
            json.loads(s) for s in (directory / name / "pending.jsonl").read_text().splitlines()
        ]
        assert [r["sample_id"] for r in pending] == [r["sample_id"] for r in english]
        assert all(
            r["prompt"] is None and r["context"] is None and r["status"] == "pending_translation"
            for r in pending
        )
        assert all(
            r["provider"] == provider and r["model_requested"] and r["model_returned"] is None
            for r in pending
        )
        assert all(r["classification_run_id"] == run.run_id for r in pending)
    assert prepare(settings, tmp_path) == report
    path = directory / "llm_translation/pending.jsonl"
    modified = json.loads(path.read_text().splitlines()[0])
    modified["prompt"] = "Human work"
    path.write_text(json.dumps(modified) + "\n")
    with pytest.raises(ValueError, match="not overwritten"):
        prepare(settings, tmp_path)
    assert "Human work" in path.read_text()
