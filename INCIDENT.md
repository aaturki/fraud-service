# Incident runbook: a secret was committed

Rehearsed in Lab 6 with a fake registry token (`FRAUD_REGISTRY_TOKEN`) that was committed to
`configs/dev.env`, deleted in the next commit, and never pushed.

## What the drill showed

Deleting the line did not remove the secret. `git log -p --all -S "<first characters of the token>"`
still printed the commit that added it, so anyone with a clone could read it. A secret that has
reached a shared repository must be treated as public from that moment.

## Response, in this order

1. **Rotate the credential now.** Revoke the leaked token in the system that issued it (for a
   GitHub token: Settings, Developer settings, revoke), issue a new one, and store it only in the
   platform's secret store (GitHub Actions secrets, the deployment's secret manager). Rotation comes
   first because cleaning history does not help anyone who already cloned or cached it.
2. **Check for use.** Review the issuer's audit log for activity with the old token between the
   push and the revocation, and record what you found here.
3. **Clean the history.** Remove the secret from every branch and tag with `git filter-repo`
   (or BFG), force-push the rewritten refs once, ask collaborators to re-clone, and ask GitHub
   support to purge cached views if the repository is public. Never do this on `main` casually:
   it rewrites the shared history, so it is an incident action, announced in advance.
4. **Stop the next one.** Keep `.env` and `*.env` in `.gitignore` and `.dockerignore`, commit
   only `configs/settings.example.env`, and run a secret scanner on every pull request
   (this repository runs gitleaks in CI). The service also masks sensitive log keys
   (`token`, `password`, `secret`, `authorization`, ...) before a line is written.

## Why the drill commits could simply be dropped

The two drill commits existed only on a local branch. `git reset --hard HEAD~2` removed them
before any push, so no remote, clone, CI log or cache ever saw the token. The moment a commit is
pushed, step 1 applies instead.

## Record

| Field | Value |
|---|---|
| Date of drill | 24 November 2026 |
| Secret | Fake registry token, drill only |
| Exposure | Local branch only, never pushed |
| Rotation needed | No (fake value); in a real leak, yes, before anything else |
| Prevention in place | `.gitignore`, `.dockerignore`, settings example file, log masking, gitleaks in CI |
