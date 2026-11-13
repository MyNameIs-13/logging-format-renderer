# dbfixlog

Structured logging for scripts that check and fix databases, plus a renderer that turns
the Log File into a single self-contained, searchable HTML Report. Python 3.6.3+, stdlib only.

| File | What it is |
|---|---|
| `dbfixlog.py` | Import this in your fix script. Writes the Log File (JSON Lines). |
| `dbfixlog_render.py` | CLI that renders a Log File into an HTML Report. |
| `report.js`, `report.css` | Read by the renderer and inlined into the Report. Keep them next to `dbfixlog_render.py`. |

The terms (Run, Dry Run, Finding, Change, Scope, Key, Label) are defined in
[GLOSSARY.md](GLOSSARY.md).

## 1. Log a Run

```python
import sqlite3
import sys

import dbfixlog


def main(write):
    con = sqlite3.connect("shop.db")
    with dbfixlog.run("fix-{ts}.jsonl", mode="write" if write else "dry",
                      title="Normalize customer emails",
                      target={"database": "shop.db"}) as log:
        rows = con.execute("select id, name, email from customers").fetchall()
        log.info("checking %d customers", len(rows), fields={"count": len(rows)})
        for cid, name, email in rows:
            with dbfixlog.scope("customer", key={"id": cid}, label={"name": name}):
                if email is None:
                    log.finding("missing-email", table="customers", key={"id": cid})
                    continue
                if email != email.lower():
                    if log.write_run:
                        con.execute("update customers set email = ? where id = ?",
                                    (email.lower(), cid))
                    log.change("customers", "update", key={"id": cid},
                               changes={"email": (email, email.lower())})
        if log.write_run:
            con.commit()


if __name__ == "__main__":
    main("--write" in sys.argv)
```

```sh
python3 fix.py            # Dry Run: Changes are logged as planned, nothing is written
python3 fix.py --write    # Write Run: Changes are applied and logged as applied
```

What the pieces do:

- `dbfixlog.run(path, mode=...)` opens the Log File and returns the logger. `{ts}` in
  the path becomes a UTC timestamp. Pass `overwrite=True` to replace an existing file.
  Its records at INFO and above are echoed to stderr (`console=False` turns that off).
- `log.info/debug/warning/error(...)` are ordinary log calls. `fields={...}` attaches
  structured values.
- `log.finding(check, msg=None, table=..., key=..., label=...)` records that a check
  found something in a row.
- `log.change(table, op, key=..., changes={field: (old, new)})` records one
  insert/update/delete. Pass `error=exc` when it failed:

  ```python
  try:
      con.execute(...)
  except sqlite3.IntegrityError as e:
      log.change("orders", "update", key={"id": oid}, changes=..., error=e)
  ```

- `dbfixlog.scope(kind, key=..., label=...)` groups the records logged inside it.
  Use it as `with` or as a decorator: `@dbfixlog.scope("phase", label={"name": "orphan-check"})`.
- `log.dry_run` / `log.write_run` tell you which mode the Run is in.

Helper modules don't need the `log` object; they get their own logger, and its records
go to whichever Run is open:

```python
log = dbfixlog.get_logger(__name__)
log.info("loading order %s", 7)
log.finding("bad-ref", table="orders", key={"id": 7})
```

Only `log` and `dbfixlog.get_logger(...)` loggers write to the Log File. Plain
`logging.getLogger(...)` calls, in your modules or in libraries, never do, and `run()`
leaves your own logging setup alone.

## 2. Render the Report

```sh
python3 dbfixlog_render.py fix-20261113T183446Z.jsonl          # writes fix-20261113T183446Z.html
python3 dbfixlog_render.py fix-....jsonl -o report.html --open  # choose the output path, open it in a browser
```

`python3 dbfixlog_render.py --help` lists all options and exit codes. The renderer
doesn't import `dbfixlog.py`, so you can copy it (with `report.js` and `report.css`)
to any machine that has the Log Files.

## Full example

[`tests/fixtures/sample_fix.py`](tests/fixtures/sample_fix.py) is a complete script
against a throwaway SQLite database, with phases, nested Scopes and a failing update.
It takes the database path and the Log File path. The database is created and seeded
when it doesn't exist yet. The usual flow is a Dry Run first, check its Report, then
the Write Run, each with its own Log File:

```sh
rm -f /tmp/shop.db    # start from the seeded data

# 1. Dry Run: nothing is changed, every Change is logged as planned
python3 tests/fixtures/sample_fix.py /tmp/shop.db /tmp/shop-dry.jsonl
python3 dbfixlog_render.py /tmp/shop-dry.jsonl --open

# 2. Write Run: the Changes are applied, one update fails on a duplicate ref
python3 tests/fixtures/sample_fix.py /tmp/shop.db /tmp/shop-write.jsonl --write
python3 dbfixlog_render.py /tmp/shop-write.jsonl --open
```

The Write Run commits, so running it again finds little left to fix. Delete
`/tmp/shop.db` to start over.
