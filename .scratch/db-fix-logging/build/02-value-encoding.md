# Value encoding

Status: open
Blocked by: 01

## What to build

The value encoder for `key`, `label`, `fields` and `changes`, wired into the writer through the seam from ticket 01. Includes the `encoders=` mapping, `strict=True` and `max_text`.

Spec: §3.5 (the full table and the rules below it). Logging never raises unless `strict=True`.

## Acceptance

- One test per table row of §3.5, including NaN/±Infinity with `allow_nan=False`, Decimal scale, aware and naive datetimes, sorted sets, `$truncated`, `$bytes` and `$unencodable`.
- Custom `encoders` take precedence. `None`-valued keys are never dropped.
- A `str()` that raises gives `$unencodable` by default and raises under `strict=True`.
