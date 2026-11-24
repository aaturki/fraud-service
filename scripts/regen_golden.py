"""Regenerate the golden file on purpose, with a stated reason, and leave an audit line.

    make regen-golden REASON="model v3.3.0 retrained on Q4 data, approved in RISK-142"
    python scripts/regen_golden.py --reason "..."          # Windows, without make

The golden file is the skew tripwire: tests/behavioural/test_model_behaviour.py fails when the
served model stops reproducing it. Regenerating it silences that alarm, so this script:

1. refuses to run without a reason of at least 20 characters;
2. refuses to rewrite scores for the SAME model version unless --allow-same-version is given
   (a changed score under an unchanged version is exactly the skew the test exists to catch);
3. reports how many rows changed and the largest change, for the pull request;
4. appends a dated entry to docs/GOLDEN_CHANGELOG.md, which CI requires whenever a golden
   file changes (job golden-guard).
"""
import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from fraud_service.adapters.sklearn_model import SklearnModel
from fraud_service.domain.entities import Transaction

MIN_REASON = 20
CHANGELOG = Path("docs/GOLDEN_CHANGELOG.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reason", default="", help="why the golden file must change")
    parser.add_argument("--golden", type=Path, default=Path("data/golden_scores_v3.csv"))
    parser.add_argument("--model", type=Path, default=Path("models/fraud_xgb_v3.joblib"))
    parser.add_argument("--allow-same-version", action="store_true",
                        help="rewrite scores although the model version did not change")
    args = parser.parse_args()

    reason = " ".join(args.reason.split())
    if len(reason) < MIN_REASON:
        print(f"Refused: give a reason of at least {MIN_REASON} characters, e.g. "
              'REASON="model v3.3.0 retrained on Q4 data, approved in RISK-142"')
        return 2

    model = SklearnModel.load(args.model)
    with args.golden.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    txns = [Transaction(transaction_id=r["transaction_id"], amount_sar=float(r["amount_sar"]),
                        channel=r["channel"], merchant_category=r["mcc"],
                        customer_id=r["customer_id"], timestamp=r["timestamp"]) for r in rows]
    # Row by row, exactly as the golden test and the service score: a few seconds for 5,000.
    new_scores = [model.predict_proba(t.to_features()).value for t in txns]
    deltas = [abs(float(r["score"]) - s) for r, s in zip(rows, new_scores, strict=True)]
    changed = sum(d > 1e-6 for d in deltas)
    previous = _last_version()
    print(f"Model {model.model_version} | {len(rows):,} rows | {changed:,} change by more "
          f"than 1e-6 | largest change {max(deltas):.3g} | previous entry: {previous or 'none'}")

    if changed == 0:
        print("Nothing to regenerate: the model reproduces the golden file.")
        return 0
    if previous == model.model_version and not args.allow_same_version:
        print(f"Refused: scores changed but the model version is still {model.model_version}. "
              "That is training/serving skew, not a new model: find the cause. If the change "
              "is intended, bump the model version or pass --allow-same-version.")
        return 3

    with args.golden.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        for row, score in zip(rows, new_scores, strict=True):
            writer.writerow({**row, "score": f"{score:.9f}"})
    with CHANGELOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {datetime.now(UTC):%Y-%m-%d} · {args.golden.name} · model "
                 f"{model.model_version}\n\n- Reason: {reason}\n- Rows: {len(rows):,}; "
                 f"changed: {changed:,}; largest change: {max(deltas):.3g}\n")
    print(f"Rewrote {args.golden} and recorded the reason in {CHANGELOG}. "
          "Paste this output into the pull request.")
    return 0


def _last_version() -> str | None:
    if not CHANGELOG.exists():
        return None
    entries = [line for line in CHANGELOG.read_text(encoding="utf-8").splitlines()
               if line.startswith("## ")]
    return entries[-1].rsplit("model ", 1)[-1].strip() if entries else None


if __name__ == "__main__":
    sys.exit(main())
