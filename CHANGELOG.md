# Changelog

All notable changes to the service contract and its behaviour. Versions follow
[Semantic Versioning](https://semver.org/); the API path stays `/v1`.

## 1.1.0: the stricter firewall

Contract change for `POST /v1/predict`. Requests that version 1.0.0 coerced silently are now
refused with `422 INVALID_REQUEST`, and `error.details` names the field.

| Field | 1.0.0 accepted | 1.1.0 requires | Why |
|---|---|---|---|
| `amount_sar` | `"249.99"` (text), `true` (became 1.0) | a JSON number, for example `249.99` | A boolean amount scored as one riyal; text amounts hide upstream serialisation bugs |
| `timestamp` | `"2026-07-05T03:30:00"` (no offset), `"2026-07-05"`, `1783222200` | ISO 8601 text with an offset, for example `2026-07-05T03:30:00+03:00` or `...Z` | `hour_of_day` and `is_night` are features: a missing offset moves the hour and changes the score |
| `merchant_category` | `"   "` (blank) | at least two visible characters | A blank category reached the model as an empty string |

What callers must do: send amounts as numbers and timestamps with an offset. Any offset is
accepted and compared as the same instant (`03:30+03:00` equals `00:30Z`).

The malformed corpus grew from 40 to 46 payloads (`payloads/malformed/`): `amount_as_string`,
`amount_as_boolean`, `timestamp_without_timezone`, `timestamp_date_only`,
`timestamp_unix_epoch` and `mcc_blank`. All 46 are rejected in the test suite.

Also in 1.1.0 (no change for well-behaved callers): `X-Trace-Id` and `X-Model-Version` on
every response, `413 PAYLOAD_TOO_LARGE` above 256 KB, `405 METHOD_NOT_ALLOWED`,
`Cache-Control: no-store` on predictions, and `model_version` in `/v1/ready`.

## 1.0.0: the workshop baseline

Layered package, strict request schema with `extra="forbid"`, one error envelope, readiness
separate from liveness, a multi-stage non-root image, the test pyramid and the CI pipeline
from Labs 1 to 6.
