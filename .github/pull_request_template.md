## What and why

<!-- One or two sentences: the change, and the reason for it. -->

## Evidence

Paste output, not promises. Tick only what you checked on this branch.

- [ ] Local gates are green: `ruff check src tests`, `mypy src/fraud_service`, `lint-imports`,
      `pytest -m "not slow" --cov --cov-fail-under=80` (paste the last line of each)
- [ ] No test, lint rule, layer contract or validation rule was weakened to make this pass
- [ ] Behavioural claims still hold: invariance, direction, batch equals one-by-one
- [ ] The malformed corpus still has at least 46 payloads and every one is rejected

## Only if it applies

- [ ] **Contract change:** `CHANGELOG.md` updated, version bumped, callers told what to send
- [ ] **Golden file touched:** regenerated only with `make regen-golden REASON="..."`; its
      output is pasted below and `docs/GOLDEN_CHANGELOG.md` has the new entry
- [ ] **New dependency or base image:** the image scan passed, or every exception is in
      `.trivyignore` with a reason, a reviewer and a revisit date
- [ ] **New numbers:** `BENCHMARKS.md` updated with the method, the machine and the date

## Hygiene

- [ ] No secrets, `.env`, virtual environments or generated files (`git status` is clean)
- [ ] Conventional commit messages (`feat:`, `fix:`, `test:`, `ci:`, `docs:`, `refactor:`)
