# Golden file changelog

Every change to a golden file (`data/golden_scores_*.csv`) is recorded here with its reason.
Write entries with `make regen-golden REASON="..."` (or `python scripts/regen_golden.py
--reason "..."`). CI (job `golden-guard`) fails any pull request that changes a golden file
without adding an entry here.

## 2026-11-23 · golden_scores_v3.csv · model v3.2.0

- Reason: baseline reference scores shipped with the model artefact in the workshop starter
  (commit 4d07f5a); not regenerated since.
- Rows: 5,000; changed: none (baseline).
