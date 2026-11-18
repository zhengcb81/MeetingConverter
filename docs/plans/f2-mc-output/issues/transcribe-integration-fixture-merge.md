# MC-OUTPUT-002 · transcribe-integration-fixture-merge

- issue_key: `transcribe-integration-fixture-merge`
- status: verified
- owner: meeting-converter
- first_seen: `b43a76a` (base commit of the F2-MC-OUTPUT card)
- evidence_class: confirmed defect in a test fixture, reproduced by execution at the
  base commit
- responsible layer: **this repository, the test fixture** — not the product

## Expected and actual

- expected: the success fixture of `tests/test_transcribe_integration.py` produces
  two paragraphs, and the translation fixture returns two translations for those two
  paragraphs — so the accepted writer accepts them.
- actual (before the fix): the fixture produced **one** paragraph and the
  translation fixture still returned **two** translations, so the writer correctly
  raised `OutputCountMismatchError` and four tests failed.
- disposition: deviation (repaired in this card; the fixture now produces two
  paragraphs and the four tests pass unchanged in their assertions)

## Impact

Test-only. No product behaviour, no output file and no published artefact was
affected. The four failures were, however, a false alarm about the product: the
already-accepted output-integrity work made the writers reject a paragraph/translation
count mismatch before touching the disk, and the old fixture hit that guard
accidentally.

The trap was specific: `merge_into_paragraphs` merges two adjacent segments into one
paragraph unless the gap between them is **greater than** the 2-second threshold.
The old fixture's second segment started at exactly the first segment's end
(`30.0`), so the gap was `0.0` and the two segments became one paragraph — while
the translation fixture, written for two paragraphs, still returned two strings.

## Occurrences

| scenario | attempt | test | expected | actual | disposition |
|---|---|---|---|---|---|
| 翻译三件齐全 | attempt-1 | TestWithTranslateThreeFiles | 2 段 / 2 译文 | 1 段 / 2 译文 | deviation |
| 翻译三件齐全 | attempt-1 | TestWithTranslateThreeFiles | 2 段 / 2 译文 | 1 段 / 2 译文 | deviation |
| 翻译三件齐全 | attempt-1 | TestWithTranslateThreeFiles | 2 段 / 2 译文 | 1 段 / 2 译文 | deviation |
| corrections 透传 | attempt-1 | TestCorrectionsAppliedInTranscribe | 2 段 / 2 译文 | 1 段 / 2 译文 | deviation |

Four failing tests, one cause: the fixture.

## Reproduction

1. The defect at the base commit — the four failures, with the mismatch named by
   the guard:

   ```powershell
   python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_transcribe_integration.py
   # at b43a76a: 4 failed, 5 passed
   # core.output.OutputCountMismatchError: translations 数量与段落数不一致: expected 1, actual 2
   ```

2. The regression that pins the repaired fixture — the translator must actually
   receive two paragraphs:

   ```powershell
   python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_transcribe_integration.py::TestWithTranslateThreeFiles::test_translator_receives_two_paragraphs
   ```

3. The negative counterpart that must stay: the real count-mismatch rejection of
   the writer itself is **not** a fixture problem and stays untouched.

   ```powershell
   python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output.py
   ```

## Ownership and root cause

- responsible layer: **test fixture**. The merge rule in `core/pipeline.py`, the
  count guard in `core/output.py` and the writers are not responsible: the guard
  rejected a translation list that did not match the paragraph count, which is
  exactly its contract.
- proven: the fixture's second segment was adjacent to the first (`start == previous
  end`), so `merge_into_paragraphs` merged them under the 2-second gap threshold,
  and the fixture's two translations had nothing to match.
- proven: the repair is in the fixture. The product was not bent to fit the
  fixture — the merge threshold, the count guard and the writers are unchanged, and
  the real mismatch rejection in `tests/test_output.py` is unchanged.
- unproven: none. This cause is fully explained by execution at the base commit.

## Fix

- commit: see the handoff's implementation SHA (`docs/plans/f2-mc-output/handoff.md`)
- change: the success fixture's second segment now starts at `35.0` instead of
  `30.0`, i.e. a 5-second gap that is **greater than** the 2-second merge
  threshold, so the fixture really produces two paragraphs. A new assertion,
  `test_translator_receives_two_paragraphs`, pins that the translator is handed
  two paragraphs and not a merged one.
- regression:
  `tests/test_transcribe_integration.py::TestWithTranslateThreeFiles::test_translator_receives_two_paragraphs`
- contract effect: none. No product file changed; only the fixture and one added
  assertion.

## Legal counterparts

- `tests/test_output.py`'s real segment-count mismatch rejection stays exactly as it
  is: the writer must keep refusing a mismatched translation before any disk write.
- `tests/test_pipeline.py::TestMergeIntoParagraphs::test_no_gap_merges` is the legal
  counterpart of this cause: an adjacent pair of segments really is one paragraph,
  and that behaviour must not change to make the fixture pass.

## Consumer re-verification

- state: verified
- who: verified in this repository on the fixed version — the four failures are gone
  and the count-mismatch rejection of `tests/test_output.py` still holds. No
  cross-repository step is needed for a test-fixture cause.
