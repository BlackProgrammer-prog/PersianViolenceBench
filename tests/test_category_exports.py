import csv
import json

import pytest

from pvb.extraction.openrouter.categories import export_categories
from pvb.extraction.openrouter.models import SampleResult
from pvb.ingestion.adapters.strongreject import adapt
from pvb.schemas.annotations import SampleAnnotation
from pvb.schemas.common import source_identity
from pvb.schemas.samples import CANONICAL_FIELDS, BenchmarkSample
from pvb.schemas.sources import SourceRecord


@pytest.mark.parametrize(
    "dataset, source_category, label, status, expected",
    [
        ("strongreject", "Violence", "out_of_scope", "classified", "other_violence"),
        ("strongreject", "Violence", "unsafe_violence", "classified", "unsafe_violence"),
        (
            "strongreject",
            "Violence",
            "benign_violence_related",
            "classified",
            "benign_violence_related",
        ),
        ("strongreject", "Violence", "out_of_scope", "abstained", "unclassified"),
        ("strongreject", "Violence", "out_of_scope", "failed", "unclassified"),
        ("strongreject", "Non-violent crimes", "out_of_scope", "classified", "out_of_scope"),
        ("harmbench", "harmful", "out_of_scope", "classified", "out_of_scope"),
    ],
)
def test_other_violence_requires_source_category_and_explicit_rejection(
    tmp_path,
    synthetic_sample,
    decision_data,
    run,
    dataset,
    source_category,
    label,
    status,
    expected,
):
    prompt = 'An original, "quoted" sample.\nمتن'
    sample = (
        adapt(
            {"category": source_category, "source": "original-source", "forbidden_prompt": prompt}
        )
        if dataset == "strongreject"
        else synthetic_sample(prompt, category=source_category)
    )
    annotation = SampleAnnotation(
        **{
            **decision_data,
            "label": label,
            "intent": "harmful" if label == "unsafe_violence" else "benign",
            "subcategories": ["V2"] if label == "unsafe_violence" else [],
        },
        annotation_id="test-annotation",
        sample_id=sample.sample_id,
        review_status="pending",
        annotation_method="llm",
        annotator_id="test-model",
        annotation_run_id=run.run_id,
        created_at=run.started_at,
        updated_at=run.started_at,
    )
    result = SampleResult(
        sample_id=sample.sample_id,
        fingerprint="a" * 64,
        status=status,
        annotation_id=annotation.annotation_id if status == "classified" else None,
    )
    url = "https://example.org/" + dataset
    digest = "b" * 64
    source = SourceRecord(
        source_id=source_identity(dataset, sample.dataset_split, url, digest),
        schema_version="1.0.0",
        dataset_name=dataset,
        dataset_split=sample.dataset_split,
        source_url=url,
        sha256=digest,
        record_count=1,
        retrieved_commit=None,
    )
    report = export_categories(
        tmp_path,
        [sample],
        [annotation] if status == "classified" else [],
        {sample.sample_id: result},
        run,
        sources=[source],
    )
    row = json.loads((tmp_path / "categorized_samples.jsonl").read_text())
    assert row["category"] == expected
    assert report["category_counts"][expected] == 1
    assert sum(report["category_counts"].values()) == 1
    assert row["source_violence_rejected_by_definition"] == (expected == "other_violence")
    assert row["source_declares_violence"] == (
        dataset == "strongreject" and source_category == "Violence"
    )
    assert BenchmarkSample.model_validate({key: row[key] for key in CANONICAL_FIELDS}) == sample
    assert row["source_registry"] == [source.model_dump(mode="json")]
    assert row["classification_label"] == (label if status == "classified" else None)
    assert report["category_counts_by_benchmark"][dataset][expected] == 1
    with (tmp_path / "categorized_samples.csv").open(newline="") as stream:
        csv_row = next(csv.DictReader(stream))
    assert csv_row["dataset_name"] == dataset and csv_row["source_category"] == source_category
    assert csv_row["original_prompt"] == prompt
    assert json.loads(csv_row["source_metadata"]) == sample.source_metadata.model_dump(mode="json")
    assert json.loads(csv_row["source_registry"])[0]["source_url"] == url
    bucket = tmp_path / "categories/other_violence.jsonl"
    assert bool(bucket.read_text()) == (expected == "other_violence")


def test_source_category_mapping_is_explicit_and_configurable(
    tmp_path, synthetic_sample, run, decision_data
):
    sample = synthetic_sample("Synthetic source-category mapping.", category="harmful")
    annotation = SampleAnnotation(
        **{**decision_data, "label": "out_of_scope", "intent": "benign", "subcategories": []},
        annotation_id="test-annotation",
        sample_id=sample.sample_id,
        review_status="pending",
        annotation_method="llm",
        annotator_id="test-model",
        annotation_run_id=run.run_id,
        created_at=run.started_at,
        updated_at=run.started_at,
    )
    result = SampleResult(
        sample_id=sample.sample_id,
        fingerprint="a" * 64,
        status="classified",
        annotation_id=annotation.annotation_id,
    )
    report = export_categories(
        tmp_path,
        [sample],
        [annotation],
        {sample.sample_id: result},
        run,
        source_violence_categories={"harmbench": ["harmful"]},
        all_samples=[
            sample,
            synthetic_sample("Not selected for classification.", category="harmful"),
        ],
    )
    assert report["category_counts"]["other_violence"] == 1
    assert report["category_rules"]["source_violence_categories"] == {"harmbench": ["harmful"]}
    assert report["source_violence_coverage"]["harmbench"]["not_selected_in_run"] == 1
    inventory = [
        json.loads(line)
        for line in (tmp_path / "source_violence_inventory.jsonl").read_text().splitlines()
    ]
    assert len(inventory) == 2
    pending = next(row for row in inventory if not row["in_this_run"])
    assert pending["category"] == "unclassified" and pending["classification_label"] is None
    assert pending["processing_status"] == "not_selected"
    assert not pending["source_violence_rejected_by_definition"]
