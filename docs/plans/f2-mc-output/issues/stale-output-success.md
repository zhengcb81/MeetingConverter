# MC-OUTPUT-001 · stale-output-success

- issue_key: `stale-output-success`
- status: verified
- owner: meeting-converter
- first_seen: `b43a76a` (base commit of the F2-MC-OUTPUT card)
- evidence_class: confirmed defect in the publication boundary, reproduced by
  execution at the base commit
- responsible layer: **this repository**, the publication boundary of
  `core/pipeline.py`

## Expected and actual

- expected: `original_translated_bilingual_current` — a run that was asked for a
  translated publication says, per output role, whether that role's bytes were
  produced **by this run** or are the previous version still sitting on disk.
- actual (before the fix): `previous_translations_only` — the run exits 0, the
  original file is new, the translation and bilingual files are byte-identical to
  the previous run, and **nothing in the repository says which is which**. A
  consumer that only looks at "the file exists" cannot tell a complete publication
  from a leftover.
- disposition: deviation (repaired in this card; the repaired code reports
  `previous_translations_only` explicitly instead of leaving it unobservable)

## Impact

The business result was never wrong: the original was written, the translation
provider was called once, the batch statistics counted the file as processed, and
the CLI exited 0. What was missing was the *provenance* of the bytes — "the file
exists" was the only signal a consumer had, and it conflated three different
situations:

1. a successful original-only run (`original_current`),
2. a run that produced only some of the requested targets (`partial_current`),
3. a run whose translation and bilingual files are the **previous** version
   (`previous_translations_only`).

The root cause is the same one the already-accepted output-integrity work named:
the three writers have a per-file atomicity guarantee, but the flow has **no
cross-file transaction and no per-round provenance**. A consumer therefore had no
way to learn whether the current `_翻译.txt` belongs to the current audio. The
translation-failure path in `core/pipeline.py` made this reachable in normal
operation: `TranslationError` is caught, the original is still written, and the
translation writers are simply not called.

## Occurrences

| scenario | attempt | step | expected | actual | disposition | evidence_ref |
|---|---|---|---|---|---|---|
| 翻译失败保留旧译文 | attempt-1 | mc-sample-stale | original_translated_bilingual_current | previous_translations_only | deviation | mc-output/73eca95d6ed6 |
| 段数错配被 writer 拒绝 | attempt-1 | synthetic | original_translated_bilingual_current | partial_current | deviation | mc-output/<run-local> |

The occurrences above are the **pre-fix publication behaviour re-created** by
suppressing the translation, so the projection observes the deviation itself. The
defect itself was first observed by executing the flow at the base commit, before
the projection existed (see the reproduction below).

## Reproduction

Three ways, none of which contacts a provider:

1. The defect at the base commit — the run exits 0 and the translation file keeps
   the previous bytes, with no signal anywhere that separates it from a fresh
   success:

   ```powershell
   python -B docs/plans/f2-mc-output/receipts/make_samples.py
   # at b43a76a this script cannot run: core/feedback.py does not exist.
   # The underlying behaviour at b43a76a is: TranslationError is caught, the
   # original is rewritten, the translation file is untouched, exit code 0.
   ```

2. The named scenario of this repository, which re-creates the pre-fix publication
   behaviour so the projection observes the deviation:

   ```powershell
   python -B docs/plans/f2-mc-output/receipts/make_samples.py
   # → docs/plans/f2-mc-output/receipts/sample-stale.jsonl
   ```

3. The regression tests, which pin the repaired contract on every publication path:

   ```powershell
   python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output_feedback.py
   ```

## Ownership and root cause

- responsible layer: **this repository**, the publication boundary of
  `core/pipeline.py`. The writers in `core/output.py`, the provider adapters, the
  batch runner and the consumer are not responsible.
- proven: the flow decided *whether* to write each output but never recorded *that
  it wrote it*. The translation-failure branch and the writer-failure branch both
  ended with a file on disk whose bytes belonged to an earlier run, and no record
  distinguished them from a fresh publication.
- proven: the repair belongs in the common responsible layer — one projection at the
  flow boundary — not in each writer. Each writer keeps its own atomic
  single-file responsibility; the flow now reports the outcome of each role.
- unproven (not this repository's fact): whether any downstream consumer has already
  been affected by the missing provenance, and how it treated an existing
  translation file. That is a consumer-side fact owned by ROOT.

## Fix

- commit: see the handoff's implementation SHA (`docs/plans/f2-mc-output/handoff.md`)
- change: a new `core/feedback.py` projects the flow boundary into
  `feedback-observation/1` rows, and `core/pipeline.py` reports each writer's role,
  its artifact identity and the phase result. `core/feedback.py` is optional and
  side-effect free: with `RESEARCH_FEEDBACK_OUT` unset nothing is written, and the
  return value, stdout, stderr and the bytes of the three output files are
  unchanged.
- regression:
  `tests/test_output_feedback.py::TestTranslationFailureKeepsStaleOutput` and
  `tests/test_output_feedback.py::TestSegmentCountMismatch` and
  `tests/test_output_feedback.py::TestBilingualWriteFailure`
- contract effect: none. The three output files, the atomic single-file replace, the
  paragraph-count guard, the skip rule, the batch statistics, the CLI exit code and
  the stdout/stderr split are unchanged; the only difference is that a per-round
  provenance record now exists when the optional sidecar is enabled.

## Legal counterparts

The repair must not turn a legal outcome into a defect. These are the counterparts
that stay `expected`:

- an original-only run (`requested-outputs` = `original_current`): a legitimately
  different request, not a missing translation;
- the documented skip when the original already exists
  (`requested-outputs` = `reused_existing`, `transcription-started` =
  `engine_not_started`, zero engine calls);
- the paragraph-count guard rejecting a mismatched translation
  (`tests/test_output.py`): the writer is right to refuse, and the refusal is
  reported as `partial_current` rather than as a success;
- an honestly unknown cost (`cost-receipt` = `cost_unknown`, disposition
  `unknown`): this repository has no usage receipt.

## Consumer re-verification

- state: pending
- who: the consumer that found the cause (ROOT) re-runs the original scenario on the
  fixed version and confirms that the translation-failure run now reports
  `previous_translations_only` instead of being indistinguishable from a complete
  publication. This repository cannot close that step on the consumer's behalf; the
  cross-repository check belongs to ROOT.
