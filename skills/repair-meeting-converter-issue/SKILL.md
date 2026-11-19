---
name: repair-meeting-converter-issue
description: Repair one adjudicated MeetingConverter (MC) issue from a repository issue card or from a given feedback-observation run reference. Use when a feedback observation names an MC-owned cause, when the transcription output publication deviates from its contract (stale translation kept, partial output, count mismatch, write failure), or when an MC deviation must be reproduced from the public entry, attributed, fixed with a RED-first regression and re-verified offline.
---

# Repair a MeetingConverter issue

One skill invocation handles **one** root cause. A cause is the `issue_key` of an
adjudicated deviation: the same `issue_key` on different audio, output mode or run
is the same cause and stays on one card.

This skill repairs only what this repository owns. It consumes this repository's
controlled replay entry and the non-executable evidence references of an issue card.
It never contacts a transcription or translation provider, never spends provider
quota, and never writes outside this repository.

## What this repository owns

| Owned here | Not owned here |
|---|---|
| `core/transcribe_one` — the single-file flow shared by the CLI and the batch runner | Which company or audio to process; the research judgement of a summary |
| `core/output.py` — the three writers, the atomic single-file replace, the paragraph-count guard | Where the output is consumed downstream |
| The paragraph merge rule and the "original already exists ⇒ skip" rule | Provider billing, quota and account state |
| The `feedback-observation/1` projection in `core/feedback.py` | Cross-repository triage, repair dispatch and the feedback loop as a whole |

A deviation whose responsible layer is another repository is not repaired here. It
is reported to ROOT with its public input, its public output and its evidence
reference.

## Inputs

Either of:

- an issue card in `docs/plans/f2-mc-output/issues/`; or
- a run reference: a `feedback-observation/1` record with its `evidence_ref`.

Read the card's sections first. They hold the expected and actual result words, the
impact, the original occurrence and its version, the runnable minimal input, the
ownership, the proven and unproven root cause, the fix and its regression case, and
the consumer re-verification state.

## Reading the observation

The sidecar rows carry stable result words; the numbers, digests and the redacted
error detail stay in this repository's own `*.details.jsonl` step log. The step
identity is `meeting-operation/<input_id>`; the evidence reference is
`mc-output/<input_id>` or `mc-output/<input_id>/<role>`.

| check_id | expected | actual words |
|---|---|---|
| `action-started` | `started` | `started`; pairs with `publication-outcome` through `terminal_check_id` |
| `transcription-started` | the same word | `engine_started` / `engine_not_started` |
| `writer-original` / `writer-translated` / `writer-bilingual` | `committed_this_round`, or `not_requested` when the mode did not ask for that role | `committed_this_round` / `not_requested` / `previous_kept` / `absent` / `failed` |
| `requested-outputs` | the requested mode: `original_current`, `original_translated_bilingual_current` or `reused_existing` | `original_current` / `original_translated_bilingual_current` / `previous_translations_only` / `stale_and_missing_translations` / `missing_translations` / `partial_current` / `reused_existing` / `write_failed` / `transcription_failed` / `translation_failed` / `unknown` |
| `publication-outcome` | `published_current`, or `reused_existing` when the skip rule applied | `published_current` / `published_partial` / `published_incomplete` / `reused_existing` / `write_failed` / `transcription_failed` / `translation_failed` / `unknown` |
| `cost-receipt` | `cost_unknown` | `cost_unknown` — this repository has no usage receipt |

Four situations must never be collapsed into one another:

- `original_current` — a successful original-only run;
- `previous_translations_only` / `stale_and_missing_translations` /
  `missing_translations` — the original is new, the translation and the bilingual
  file are the previous version (or absent);
- `partial_current` — some requested targets were committed and another writer
  failed;
- `reused_existing` — the documented skip: this round produced nothing.

`published_partial` (some targets were committed and another writer failed) and
`published_incomplete` (this round produced no translation at all) are two
different terminal states. `write_failed` is the terminal state of a write
failure that committed nothing at all.

`expected` and `actual` differ exactly when the disposition is `deviation`, except
for `cost-receipt`, which is `unknown` by construction, and for a terminal state of
`unknown` — a run that was stopped without a credible terminal state. The terminal
row is written **last**, so a sidecar that was not written completely ends without
a `publication-outcome`: a start row without a matching terminal row also means
that the terminal state is unknown.

`issue_key` is present only where the owner has adjudicated the cause
(`stale-output-success` for a previous version of the translation or the bilingual
file that really survived on disk). Its absence means "not adjudicated yet", not
"no problem": `missing_translations` shares the responsible layer but has no
surviving old file to point at.

Two files are written per run: the sidecar itself (`RESEARCH_FEEDBACK_OUT`) and
its sibling `*.details.jsonl` step log. A consumer that collects the observation
has to collect both.

## Procedure

### 1. Fix the facts before touching code

State, in the card's own terms, and verify each one:

1. **Expected** — the requested mode: `original_current` for an original-only run,
   `original_translated_bilingual_current` for a translated run.
2. **Actual** — the result word this run produced.
3. **Version** — the code version of the observed run. The observation's `version`
   field names the projection version; the reviewed source SHA belongs to the
   handoff, not to the observation.
4. **Real input source** — where the input genuinely came from: a synthetic fixture,
   a recorded original, or a fault injection. A fixture is not a live fact and must
   never be reported as one.

If any of the four cannot be established, the issue is **not yet actionable**: record
what is missing and stop. Do not guess a cause.

### 2. Reproduce from the public entry

Reproduce through the public entry, not through an internal helper:

```python
from core import transcribe_one
transcribe_one(engine, audio_path, output_dir, translator_obj=translator, force=True)
```

`core.batch.run_batch` is the batch entry over the same function. The synthetic
audio, the stub engine and the stub translator are the fixtures of
`tests/test_output_feedback.py`; no provider, credential or real audio is needed.

Find the **first** place where the run departs from the contract, not the first
place where the symptom appears.

### 3. Look for sibling entries and legal counterparts

- Sibling entries: every other place in this repository that performs the same step
  (a second writer, a second CLI path, the batch runner, the skip rule). A fix that
  patches one path and leaves its siblings inconsistent is not a fix.
- Legal counterparts: the runs that look similar but are correct (a refusal that is
  right, a count mismatch that is right, a skip that is right, an honestly unknown
  cost). Use them to keep the repair from turning a legal outcome into a defect,
  and to detect over-fitting.

### 4. Attribute the cause

Name exactly one responsible layer and say why the others are not:

| Layer | Meaning |
|---|---|
| Business error | The product logic is wrong. Fix it here. |
| Test fixture | The fixture, clock or injected transport is wrong. Fix the fixture; never bend the product to fit it. |
| Deployment environment | The host, permissions, clock or path broke it. Record the recovery condition; the product stays as it is. |
| External condition | The provider, account or network refused. Record it as a fact of the environment; do not repair the product for it. |

### 5. Write the RED first

From the old error and the legal counterpart, write the failing test before the fix,
in `tests/test_output_feedback.py` (publication deviations) or
`tests/test_output.py` (writer contract). The RED must:

- run through the public entry;
- fail for the recorded reason, not for an import or a setup error;
- pass unchanged after the fix.

Record the RED output as a receipt. A repair without a recorded RED is not accepted.

### 6. Fix the common responsible layer

Repair the layer that owns the cause, not the symptom's first appearance. Keep the
public contract: the three output files, the atomic single-file replace, the
paragraph-count guard, the skip rule, the batch statistics, the CLI exit code and the
stdout/stderr split stay as they are unless the card explicitly says the contract
itself is wrong.

Record the fix and its test in this repository's plan directory
(`docs/plans/f2-mc-output/`); the root `progress.md` and `findings.md` are history and
are not status entries.

### 7. Targeted GREEN, then re-verify the original scenario

- Run the new test alone, then the focused combination, then the wider regression:

  ```powershell
  python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output.py tests/test_pipeline.py tests/test_transcribe_integration.py tests/test_output_feedback.py
  ```

- Re-run the original scenario through the public entry and confirm that the
  observation of that cause is now `expected`.
- A repair is only complete when the original scenario no longer deviates.

### 8. Close the loop

Record in the card:

- the fix version (the reviewed source SHA, not the SHA of the receipt that mentions
  it);
- the regression case (the exact command and its result);
- the consumer re-verification state: `pending` for the consumer that found the
  cause, `verified` once that consumer re-ran the original scenario on the fixed
  version;
- the remaining items that belong to another repository.

## Stop conditions

- Same version, same input, same failure → do **not** run the loop again. Report that
  the repair attempt did not move the failure.
- The cause is not adjudicated (`disposition` is `expected` or `unknown`) → this is
  not an issue to repair. A legal refusal, a documented skip and an honestly unknown
  cost are all normal outcomes.
- The reproduction needs a live provider, a paid account or a credential → out of
  scope for this offline skill. Record what is missing and the recovery condition.
- The responsible layer is another repository → report to ROOT with the public input,
  the public output and the evidence reference; do not edit the other repository.

## Boundaries

- The three output files, the atomic single-file replace, the paragraph-count guard,
  the skip rule, the batch statistics, the CLI exit code and the stdout/stderr split
  are frozen. A repair states its effect on them explicitly.
- The feedback sidecar is optional: enabling it must not change the return value, the
  stdout, the stderr or the bytes of any output file. The sidecar's own write latency
  must therefore stay outside every measured region — a repair that writes to the
  sidecar inside a timed block changes the published timing and therefore the bytes
  of the output files. A sidecar write that fails never changes the business outcome:
  the run keeps its own exit code, its own result and its own retry behaviour, and
  the incomplete diagnostic is reported on this repository's local diagnostic channel
  (the logger) only.
- Originals and formal run artefacts stay with their owner. The observation carries
  only stable result words and opaque, credential-free references. This repository's
  own step log is redacted as well: no absolute path, no audio name, no transcript
  body and no credential — only the native exception class, a redacted message, the
  per-role digests and the metrics. The unredacted facts stay in the repository's
  ordinary log output.
