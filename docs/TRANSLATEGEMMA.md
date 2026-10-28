# Local TranslateGemma 4B

This extends `pvb.translation`; it does not create a web server, container, or new project.
The local model is **google/translategemma-4b-it**, distinct from Google Cloud Translation
Basic v2 and the paid GapGPT LLM. It generates faithful English-to-Persian translations,
without instructions to adapt, answer, explain, or change the benchmark questions.

Official model/access/template documentation:
<https://huggingface.co/google/translategemma-4b-it>.

## Setup

```bash
uv sync --extra local-translation
uv run --extra local-translation python -m pvb.translation.local --mode check
```

The optional dependency group keeps PyTorch out of ordinary ingestion/extraction installs.
The CUDA 12.4 PyTorch 2.6.0 wheel is pinned for this Linux x86_64/Python 3.10 environment;
Transformers is pinned to 4.57.6. Exact transitive versions are recorded in `uv.lock`.
Do not run a bare `uv sync` before local inference: it can remove optional dependencies.

Accept Gemma terms using your own Hugging Face account on the official model page.
Put a read token from the same account into `.env` as `HF_TOKEN`. Never put it in
commands, output artifacts, or Git. Existing Hugging Face cached authentication also works.

```dotenv
HF_TOKEN=
PVB_TRANSLATEGEMMA_MODEL_PATH=models/translategemma-4b
PVB_TRANSLATEGEMMA_REVISION=main
PVB_TRANSLATEGEMMA_MAX_INPUT_TOKENS=2048
PVB_TRANSLATEGEMMA_MAX_NEW_TOKENS=512
PVB_TRANSLATEGEMMA_ALLOW_CPU_OFFLOAD=false
PVB_TRANSLATEGEMMA_GPU_RESERVE_MIB=256
```

```bash
uv run --extra local-translation python -m pvb.translation.local --mode download
uv run --extra local-translation python -m pvb.translation.local --mode smoke --block-network
uv run --extra local-translation python -m pvb.translation.local --mode translate --block-network
```

On slow connections, `--mode download --download-workers 32` uses resumable HTTP ranges
against the same official pinned Hugging Face weights. Ranges and final files are hashed;
partial downloads stay under the model's `.cache/` directory. The ordinary two-worker
Hugging Face downloader remains the default.

Download resolves the requested revision to an exact commit, downloads the original weights,
checks LFS checksums, and writes a local manifest with sizes and SHA256 checksums. Existing
complete downloads are verified and reused. No manifest means the download is incomplete.
The model directory is ignored by Git. Download never happens inside `translate()`.

`--block-network` rejects Python socket connections, in addition to both HF offline
environment settings and `local_files_only=True`. Use it in a fresh process after download.
It is an application-level offline test, not an operating-system network namespace.

## Reusable service

To run dependency setup, download, the five offline smoke tests in a fresh process,
and the 54-sample translation sequentially:

```bash
uv run --no-sync python -m pvb.translation.workflow
```

`runs/translation/translategemma_workflow_status.json` records the actual current stage.
The workflow stops on any failed prerequisite and never marks all samples translated
unless the translation CLI succeeds. It makes no paid API requests.

```python
from pvb.translation import TranslationService

translator = TranslationService()  # Lazy: no weights loaded yet.
print(translator.translate("Which of the following statements is NOT correct?"))
print(translator.translate_batch(["First text.", "Second text."]))
print(translator.last_metrics)
```

The model loads once per service instance. A lock serializes inference; batch size is one.
NF4 double quantization is used, with BF16 if supported and otherwise FP16. GPU-only
placement is the default, verified on this machine. CPU offload can be enabled by configuration and bounded by currently available RAM, accounting for the fact
that offloaded modules can remain unquantized. No automatic alternative model is used.
An explicit failure is returned on CUDA OOM or insufficient memory. Free other GPU/RAM
applications before retrying; do not kill unrelated processes or change drivers automatically.

The observed machine has **4 GiB VRAM**, not the 8 GiB in the initial request. Available
memory fluctuates because the desktop and other applications share it. A successful
download alone does not establish that inference fits this machine.

Input limits include template tokens; oversized text is rejected rather than truncated.
Output hitting its token limit is rejected rather than saved as a successful translation.
Empty/whitespace inputs are preserved without loading the model. No custom postprocessing
replaces terms, numbers, named entities, cultural references, or formulas.

## Results and reproducibility

`runs/translation/translategemma-smoke/smoke_report.json` records the five real test
translations, CUDA-synchronized timings, load time, GPU memory, and runtime versions,
**only after actual inference succeeds**. Unit-test stub text is not a model result.

`--mode translate` requires the original 54 unique selected samples. It writes:

- `runs/translation/translategemma-<identity>/samples.jsonl`: untouched source record,
  Persian prompt/context, source hashes, model commit, NF4 mode, timing, pending human
  review, and the independent cultural audit. Prior labels are inherited, not revalidated.
  It uses the existing `llm_translation` variant with `translation_engine=translategemma`
  and explicit local provider/model metadata, rather than silently calling GapGPT.
- `english.jsonl`: all 54 exact originals with matching sample IDs.
- `translations.csv`: paired source/translation and group membership.
- `embedding_pairs.jsonl`: exact English/raw Persian pairs, group membership and explicit
  empty fields for future human references and embedding scores; no invented comparison.
- `run.json`, `summary.json`, `errors.json`: provenance, completion counts and actual errors.

Each completed sample is saved atomically. Repeating the same command resumes the same
identity and verifies checkpoints before reuse. Source/model/settings/implementation changes
produce a separate run. Failed translations are never filled with guessed text.
The separate GapGPT/Google API translation plans are not marked as completed by this command.
No paid API requests are needed for local TranslateGemma.

## Next experiment: translation disagreement

The original cultural audit has **two** predicted localization-dependent cases, and **one**
provider-refused, culturally unassessed case. That third case must remain a separate group;
it is not evidence of cultural dependence. The audit was a hypothesis from English text,
not a ground-truth evaluation of Persian translations.

First translate all 54 **without human intervention** and freeze those outputs. Then obtain
an independently reviewed faithful Persian reference for the same texts, with a separate
expert-localized version where needed. Keep all versions rather than editing the first
translation in place. Use blinded human judgments of semantic preservation, violence
construct, local legal/institutional context, negation, quantities, and question-vs-answer
behavior. A culturally adapted question can intentionally change meaning, so its distance
from English alone cannot establish which version is valid for the benchmark.

For the embedding stage choose a single multilingual model validated for English/Persian,
pin its revision and preprocessing, and record similarities for English↔raw Persian,
English↔human-reviewed Persian, and raw↔reviewed Persian. Compare the flagged group with
the other 51 samples as a control; do not choose thresholds after seeing desired results.
Embed the text fields only, never the audit rationale, category labels, or serialized metadata.

Cosine distance `1 - cosine_similarity` is **not a percentage of translation mistakes**
and cannot prove cultural harm or semantic equivalence. Report it as a model score. A
defensible error percentage is `100 × adjudicated failures / evaluated samples`, with
a predefined rubric and uncertainty interval. With just three cases each case changes
that percentage by 33.3 points; the sample cannot support a general population claim.
No embedding scores or invented human references are generated in this setup stage.

## Actual local verification

The model completed all five offline smoke translations on the RTX 3050 Ti (4 GiB),
with CPU offload disabled. See `runs/translation/translategemma-smoke/smoke_report.md`
and the JSON report for real outputs, synchronized timings and memory measurements.
The prior automatic CPU-offload attempt exited with signal 9 while loading; its
download was already complete. Reusing the local weights with GPU-only placement succeeded.
