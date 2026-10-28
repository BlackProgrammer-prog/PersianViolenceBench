"""Native tests skip only if the actual optional engine cannot be loaded."""

import subprocess
import sys

import pytest

from pvb.extraction.pipeline import annotation_for
from pvb.ingestion.normalize import collect
from pvb.schemas.annotations import Decision


@pytest.fixture
def native(tmp_path):
    n = pytest.importorskip("nexoradb")
    if n.__version__ != "0.2.1":
        pytest.skip("only native 0.2.1 is verified")
    from pvb.storage.nexoradb import NexoraRepository

    return NexoraRepository(tmp_path / "native")


def test_native_contract_and_annotation_history(native, snapshot, run, decision_data):
    samples, sources = collect(snapshot[0])
    native.ingest(sources, samples)
    native.ingest(sources, samples)
    native.upsert_samples(samples)
    assert native.get_sample(samples[0].sample_id) == samples[0]
    assert native.get_source(sources[0].source_id) == sources[0]
    assert len(native.list_samples(dataset_name="harmbench", dataset_split="validation")) == 1
    assert native.get_sample("missing") is None
    native.save_run(run)
    a = annotation_for(samples[0], Decision(**decision_data), run, "rule")
    native.add_annotations([a])
    native.add_annotations([a])
    assert native.list_annotations(a.sample_id) == [a]
    with pytest.raises(ValueError, match="immutable"):
        native.add_annotations([a.model_copy(update={"rationale": "overwrite"})])
    assert native.list_annotations() == [a]
    with pytest.raises(ValueError):
        native.ingest(sources, samples[:1])
    assert len(native.list_samples()) == 2


def test_native_transaction_rollback(native):
    from pvb.storage.nexoradb.repository import checked

    db = native.engine
    checked(db.create_collection("probe"))
    tx = db.begin_transaction()
    checked(db.insert_one_tx(tx, "probe", '{"_id":"x","unicode":"فارسی","array":[1],"nil":null}'))
    assert db.find_by_id_tx(tx, "probe", "x").success
    checked(db.rollback_transaction(tx))
    assert not db.find_by_id("probe", "x").success
    checked(db.insert_many("probe", ['{"_id":"a"}', '{"_id":"b"}']))
    assert db.get_collection_size("probe") == 2


def test_native_reopen_after_process_exit(tmp_path):
    pytest.importorskip("nexoradb")
    path = str(tmp_path / "reopen")
    script = """
import nexoradb, sys
engine=nexoradb.DocEngine(sys.argv[1])
if sys.argv[2]=='write':
 assert engine.create_collection('probe').success
 assert engine.insert_one('probe','{"_id":"persistent","value":"فارسی"}').success
else:
 import json
 result=engine.find_by_id('probe','persistent')
 assert result.success and json.loads(result.data)['value']=='فارسی'
"""
    for mode in ("write", "read"):
        subprocess.run([sys.executable, "-c", script, path, mode], check=True, capture_output=True)


def test_native_verified_filter_update_delete(native):
    import json

    import nexoradb as n

    from pvb.storage.nexoradb.repository import checked

    db = native.engine
    checked(db.create_collection("crud_probe"))
    checked(db.insert_one("crud_probe", '{"_id":"a","kind":"fixture","count":1}'))
    condition = n.Condition.leaf("kind", n.Op.EQ, "fixture", n.ValueType.String)
    rows = json.loads(checked(db.find_many("crud_probe", condition)))
    assert len(rows) == 1 and rows[0]["_id"] == "a"
    spec = n.UpdateSpec()
    spec.set("kind", "updated")
    checked(db.update_by_id("crud_probe", "a", spec))
    assert json.loads(checked(db.find_by_id("crud_probe", "a")))["kind"] == "updated"
    checked(db.delete_by_id("crud_probe", "a"))
    assert not db.find_by_id("crud_probe", "a").success
