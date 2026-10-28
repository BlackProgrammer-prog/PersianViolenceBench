import csv
from pathlib import Path

import pytest
import yaml

from pvb.ingestion.adapters.harmbench import COLUMNS as HB_COLUMNS
from pvb.ingestion.adapters.strongreject import COLUMNS as SR_COLUMNS


@pytest.fixture
def hb_record():
    return {
        "Behavior": '  متن فارسی, "quoted"\r\nnext line\t ',
        "FunctionalCategory": "standard",
        "SemanticCategory": "original category",
        "Tags": " tag1, tag2 ,,tag1 ",
        "ContextString": "  context\r\nفارسی  ",
        "BehaviorID": "original-id",
    }


@pytest.fixture
def sr_record(hb_record):
    return {
        "category": "original category",
        "source": "original provider",
        "forbidden_prompt": hb_record["Behavior"],
    }


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def snapshot(tmp_path, hb_record, sr_record):
    write_csv(tmp_path / "hb.csv", HB_COLUMNS, [hb_record])
    write_csv(tmp_path / "sr.csv", SR_COLUMNS, [sr_record])
    config = {
        "schema_version": "1.0.0",
        "root": ".",
        "sources": [
            {
                "dataset_name": "harmbench",
                "dataset_split": "validation",
                "path": "hb.csv",
                "source_url": "https://example.org/hb.csv",
                "expected_record_count": 1,
            },
            {
                "dataset_name": "strongreject",
                "dataset_split": "unspecified",
                "path": "sr.csv",
                "source_url": "https://example.org/sr.csv",
                "expected_record_count": 1,
            },
        ],
    }
    config_path = tmp_path / "datasets.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path, tmp_path / "normalized"


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def decision_data():
    return {
        "label": "unsafe_violence",
        "subcategories": ["V3", "V4"],
        "intent": "harmful",
        "target": "other_person",
        "actionability": "medium",
        "risk_severity": "high",
        "confidence": 0.0,
        "rationale": "Synthetic request for physical harm to others.",
        "evidence": [],
        "requires_human_review": True,
    }


@pytest.fixture
def run():
    from pvb.schemas.annotation_runs import AnnotationRun

    return AnnotationRun(
        run_id="run-test",
        method="rule_based",
        configuration={},
        input_dataset_fingerprint="a" * 64,
        started_at="2026-10-24T00:00:00Z",
        status="running",
        sample_count=2,
    )


@pytest.fixture
def synthetic_sample():
    from pvb.ingestion.adapters.harmbench import adapt

    def make(prompt, context="", split="validation", category="untrusted category"):
        return adapt(
            {
                "Behavior": prompt,
                "ContextString": context,
                "FunctionalCategory": "contextual" if context else "standard",
                "SemanticCategory": category,
                "Tags": "",
                "BehaviorID": prompt,
            },
            split,
        )

    return make
