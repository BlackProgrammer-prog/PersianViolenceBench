from pvb.extraction.duplicates import duplicate_report
from pvb.ingestion.adapters.strongreject import adapt


def test_exact_normalized_cross_source(synthetic_sample):
    samples = [
        synthetic_sample("Sample text"),
        synthetic_sample("  SAMPLE   text  "),
        adapt({"category": "unchanged", "source": "fixture", "forbidden_prompt": "Sample text"}),
    ]
    report = duplicate_report(samples)
    assert len(report["exact_groups"]) == 1
    assert report["exact_groups"][0]["cross_source"]
    assert len(report["normalized_text_groups"]) == 1
    assert len(report["normalized_text_groups"][0]["samples"]) == 3
    assert (
        len(duplicate_report(samples, casefold=False)["normalized_text_groups"][0]["samples"]) == 2
    )
    assert samples[1].original_prompt == "  SAMPLE   text  "


def test_unicode_and_context_are_separate(synthetic_sample):
    samples = [synthetic_sample("Ａ"), synthetic_sample("A", context="different context")]
    assert len(duplicate_report(samples)["normalized_text_groups"]) == 1
    assert not duplicate_report(samples)["exact_groups"]
    assert not duplicate_report(samples, unicode_form="NFC")["normalized_text_groups"]
