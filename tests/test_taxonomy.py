import pytest
import yaml

from pvb.extraction.taxonomy import Taxonomy, load_taxonomy


def test_official_taxonomy(project_root):
    t = load_taxonomy(project_root / "configs/taxonomy.yaml")
    assert t.taxonomy_id == "pvb-violence" and t.version == "1.0.0"
    assert set(t.subcategories) == {"V1", "V2", "V3", "V4", "V5"}


@pytest.mark.parametrize(
    "change",
    [
        {"version": "2.0.0"},
        {"subcategories": {"V6": "bad"}},
        {"labels": ["unsafe_violence"]},
        {"rules": []},
        {"unexpected": True},
    ],
)
def test_invalid_taxonomy(project_root, change):
    data = yaml.safe_load((project_root / "configs/taxonomy.yaml").read_text())
    with pytest.raises(ValueError):
        Taxonomy.model_validate({**data, **change})
