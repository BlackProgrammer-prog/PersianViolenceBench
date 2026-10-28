"""Deterministic pilot selection from development sources only.

Proxy strata are sampling heuristics, never annotation labels. If a likely-benign
stratum is absent, report that gap instead of inventing benign dataset records.
"""

import random
import re
from collections import Counter, defaultdict


def proxy_stratum(sample):
    text = sample.original_prompt.casefold()
    if re.search(
        r"\b(history|historical|prevent|prevention|journalis|educational|legal analysis)\b", text
    ):
        return "potential_discussion_or_pretext"
    if re.search(r"\b(kill|harm|attack|threat|weapon|violence|assault)\b", text):
        return "potential_harm"
    return "unclear_or_other"


def select_pilot(samples, seed: int, count: int = 20):
    development = [s for s in samples if s.dataset_split != "test"]
    if len(development) < count:
        raise ValueError("pilot requires at least 20 development samples")
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for sample in sorted(development, key=lambda s: s.sample_id):
        buckets[(sample.dataset_name, proxy_stratum(sample), sample.source_category)].append(sample)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    # First cover each source/proxy combination, then category strata round robin.
    keys = sorted(buckets)
    rng.shuffle(keys)
    selected, selected_ids = [], set()
    combinations = sorted({key[:2] for key in keys})
    for combination in combinations:
        key = next(key for key in keys if key[:2] == combination and buckets[key])
        sample = buckets[key].pop()
        selected.append(sample)
        selected_ids.add(sample.sample_id)
    while len(selected) < count:
        for key in keys:
            if buckets[key] and len(selected) < count:
                sample = buckets[key].pop()
                selected.append(sample)
                selected_ids.add(sample.sample_id)
    return selected, {
        "seed": seed,
        "sample_count": len(selected),
        "test_samples": 0,
        "source_counts": dict(Counter(s.dataset_name for s in selected)),
        "category_counts": dict(Counter(s.source_category for s in selected)),
        "proxy_counts": dict(Counter(proxy_stratum(s) for s in selected)),
        "limitation": "Proxy strata are not verified harmful/benign labels. No guaranteed benign or ambiguous ground truth is claimed.",
    }
