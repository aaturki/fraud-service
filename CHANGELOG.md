# Changelog

All notable changes to the service contract and its behaviour. Versions follow
[Semantic Versioning](https://semver.org/); the API path stays `/v1`.

## 1.1.1: one instant, one score

A fix: callers send exactly what they sent before. Version 1.1.0 promised that any offset is
compared as the same instant, but the features read the clock in whatever offset the caller
wrote. The model learned its hours in UTC (every training row is `+00:00`), so a caller using
Riyadh time got a score three hours off. For the transaction in `payloads/sample.json` at
00:30 UTC:

| The same instant, written as | Hour the model saw in 1.1.0 | Score in 1.1.0 | Score in 1.1.1 |
|---|---|---|---|
| `2026-07-05T00:30:00+00:00` | 0 | 0.53180 | 0.53180 |
| `2026-07-05T03:30:00+03:00` | 3 | 0.62614 | 0.53180 |

The domain now converts every timestamp to UTC before any feature is computed. A time without
an offset, which the API refuses, is read as UTC inside the domain. Callers who send UTC see
no change, and all 5,000 golden rows still reproduce. Tests at three levels lock it: four
spellings of one instant give one hour (unit), the model receives the UTC hour through the API
(integration), and the real artefact gives one score for one instant (behavioural).

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
