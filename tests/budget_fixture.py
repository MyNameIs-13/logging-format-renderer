"""Budget fixture generator (SPEC §7): a Log File with realistic entropy.

Written through dbfixlog.py itself, so generating it also exercises the writer end to end.
It produces random ids, names and free text, mixed field counts, Scopes nested up to four
deep (phase > customer > order > line), Findings, failed Changes and Scopes that raise.
The JSONL compresses at most ~5x with gzip, unlike the research branch's small-vocabulary
data (~9.5x).

    python3 tests/budget_fixture.py N OUT.jsonl [SEED]
"""
import logging
import os
import random
import string
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dbfixlog  # noqa: E402

SYLLABLES = ["ka", "lo", "mi", "ner", "sa", "tu", "vel", "dor", "an", "be", "cri", "fo",
             "gal", "hu", "is", "jo", "ken", "lu", "mar", "no", "op", "pra", "qui", "ro",
             "st", "ti", "ul", "vo", "wen", "xa", "yr", "zel"]
SUFFIXES = ["BV", "GmbH", "Ltd", "Inc", "& Co", "Group", "Trading", "Holding", ""]
WORDS = ("order customer invoice line stock price total amount delivery address street "
         "postcode payment refund credit discount supplier warehouse batch shipment carrier "
         "status pending blocked missing duplicate orphan expired archived checked updated "
         "removed inserted mismatch rounding currency tax vat reference contract account "
         "balance overdue reminder note manual import export sync legacy migrated").split()
CITIES = ["Utrecht", "Leiden", "Gent", "Antwerpen", "Köln", "Lille", "Bremen", "Delft",
          "Zwolle", "Breda", "Aachen", "Namur", "Haarlem", "Arnhem", "Brugge", "Liège"]
CHECKS = ["no-lines", "negative-total", "duplicate-email", "missing-address",
          "stale-price", "orphan-line", "bad-postcode", "currency-mismatch"]
TABLES = ["orders", "order_lines", "customers", "invoices", "shop.addresses", "stock"]
STATUSES = ["open", "paid", "shipped", "cancelled", "on_hold", "returned"]


class _Clock(object):
    """A simulated wall clock: each reading advances it by a random database round trip,
    so timestamps vary as in a real script instead of repeating within one millisecond."""

    def __init__(self, seed):
        self.r = random.Random(seed + 1)
        self.now = 1794600000.0 + self.r.uniform(0, 86400 * 30)

    def time(self):
        self.now += self.r.expovariate(1 / 0.004)
        return self.now

    def time_ns(self):
        return int(self.time() * 1e9)


class _Gen(object):
    def __init__(self, n, seed):
        self.r = random.Random(seed)
        self.left = n - 2  # run_start and run_end are written by run()
        # Twenty thousand pseudo-words, drawn Zipf-like, beside the common domain words.
        self.vocab = ["".join(self.r.choice(string.ascii_lowercase)
                              for _ in range(self.r.randint(2, 10))) for _ in range(20000)]

    def spend(self, k=1):
        self.left -= k

    def ident(self):
        return self.r.randint(10000, 99999999)  # surrogate keys from a big, gappy range

    def name(self):
        r = self.r
        word = "".join(r.choice(SYLLABLES) for _ in range(r.randint(2, 4))).capitalize()
        return (word + " " + r.choice(SUFFIXES)).strip()

    def text(self, lo=3, hi=14):
        r = self.r
        words = [r.choice(WORDS) if r.random() < 0.3 else
                 self.vocab[(int(r.paretovariate(0.3)) - 1) % len(self.vocab)]
                 for _ in range(r.randint(lo, hi))]
        while r.random() < 0.85:  # references, hashes, amounts: values that never repeat
            words.insert(r.randrange(len(words) + 1),
                         self.token() if r.random() < 0.7 else str(self.money()))
        return " ".join(words)

    def token(self):
        r = self.r
        kind = r.randrange(3)
        if kind == 0:
            return "%016x" % r.getrandbits(64)
        if kind == 1:
            return "INV-%d-%05d" % (r.randint(2019, 2026), r.randint(0, 99999))
        return "".join(r.choice(string.ascii_letters + string.digits) for _ in range(r.randint(6, 12)))

    def email(self, name):
        return "%s.%d@%s.example" % (name.split()[0].lower(), self.r.randint(1, 999),
                                     self.r.choice(SYLLABLES) + self.r.choice(SYLLABLES))

    def money(self):
        return round(self.r.uniform(-50, 5000), 2)

    def fields(self):
        """0 to 10 fields drawn from a pool of differently typed values."""
        r = self.r
        pool = [
            ("customer_id", lambda: self.ident()),
            ("total", self.money),
            ("city", lambda: r.choice(CITIES)),
            ("note", lambda: self.text(2, 10)),
            ("ref", self.token),
            ("request_id", lambda: "%08x-%04x-%04x" % (r.getrandbits(32), r.getrandbits(16), r.getrandbits(16))),
            ("contact", lambda: self.email(self.name())),
            ("count", lambda: r.randint(0, 500)),
            ("ok", lambda: r.random() < 0.7),
            ("missing", lambda: None),
            ("tags", lambda: r.sample(WORDS, r.randint(1, 4))),
            ("ms", lambda: round(r.expovariate(0.05), 1)),
            ("addr", lambda: {"street": self.text(1, 2).title(), "no": r.randint(1, 300),
                              "postcode": "%04d %s" % (r.randint(1000, 9999),
                                                       "".join(r.choice(string.ascii_uppercase) for _ in range(2)))}),
        ]
        return dict(f() for f in [lambda p=p: (p[0], p[1]()) for p in r.sample(pool, r.randint(0, 10))])


def generate(path, n, seed=0):
    """Write a Write Run of about ``n`` records (never fewer) to ``path``."""
    g = _Gen(n, seed)
    clock = _Clock(seed)
    real = time.time, time.time_ns
    time.time, time.time_ns = clock.time, clock.time_ns
    try:
        _write(path, n, seed, g)
    finally:
        time.time, time.time_ns = real
    return path


def _write(path, n, seed, g):
    r = g.r
    with dbfixlog.run(path, mode="write", title="Budget fixture %d" % n, console=False,
                      overwrite=True, description="Synthetic Log File for the SPEC §7 budgets",
                      target={"database": "shop_bench", "host": "db-%d" % seed},
                      fields={"seed": seed, "records": n}) as log:
        sync = dbfixlog.get_logger("shop.sync")
        log.info("connected", fields={"server": "pg-%x" % r.getrandbits(24), "pool": 4})
        g.spend()
        phase_no = 0
        while g.left > 0:
            phase_no += 1
            with log.scope("phase", label={"name": "pass %d" % phase_no},
                           msg=g.text(2, 5)):
                g.spend(2)
                for _ in range(r.randint(200, 600)):
                    if g.left <= 0:
                        break
                    _customer(g, log, sync)
        g.left = 0


def _customer(g, log, sync):
    r = g.r
    cid, name, city = g.ident(), g.name(), r.choice(CITIES)
    try:
        with log.scope("customer", key={"id": cid}, label={"name": name, "city": city},
                       fields={"email": g.email(name)} if r.random() < 0.6 else None):
            g.spend(2)
            for _ in range(r.randint(0, 4)):
                log.debug(g.text(), fields=g.fields())
                g.spend()
            if r.random() < 0.15:
                log.finding(r.choice(CHECKS), g.text(3, 8), table="customers",
                            key={"id": cid}, label={"name": name, "city": city},
                            level=r.choice([logging.INFO, logging.WARNING, logging.WARNING,
                                            logging.ERROR]),
                            fields=g.fields() or None)
                g.spend()
            for _ in range(r.randint(0, 4)):
                _order(g, log, sync, cid)
            if r.random() < 0.01:
                raise RuntimeError("lock timeout on customer %d after %dms"
                                   % (cid, r.randint(1000, 30000)))
    except RuntimeError:
        log.warning("skipped customer %d, continuing" % cid)
        g.spend()


class _NoScope(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _scope_or_not(g, log, p, kind, **kw):
    """A Scope with probability p (each costs two records), else nothing."""
    if g.r.random() < p:
        g.spend(2)
        return log.scope(kind, **kw)
    return _NoScope()


def _order(g, log, sync, cid):
    r = g.r
    oid = g.ident()
    with _scope_or_not(g, log, 0.45, "order", key={"id": oid}, label={"ref": g.token()}) as sc:
        scoped = not isinstance(sc, _NoScope)
        if r.random() < 0.6:
            sync.info(g.text(), fields=g.fields())
            g.spend()
        for line_no in range(1, r.randint(1, 5)):
            with _scope_or_not(g, log, 0.15 if scoped else 0, "line",
                               key={"order_id": oid, "line_no": line_no}) as line:
                _line_change(g, sync, oid, line_no)
                if not isinstance(line, _NoScope) and r.random() < 0.5:
                    sync.debug(g.text(), fields=g.fields())
                    g.spend()
        if r.random() < 0.1:
            log.finding(r.choice(CHECKS), g.text(2, 9), table="orders", key={"id": oid},
                        label={"customer": cid}, fields=g.fields() or None)
            g.spend()
        op = r.random()
        if op < 0.5:
            old, new = r.sample(STATUSES, 2)
            changes = {"status": [old, new]}
            if r.random() < 0.4:
                changes["total"] = [g.money(), g.money()]
            if r.random() < 0.2:
                changes["note"] = [None, g.text(4, 12)]
            if r.random() < 0.3:
                who = g.name()
                changes["ship_to"] = [g.name(), who]
                changes["email"] = [g.email(g.name()), g.email(who)]
            if r.random() < 0.03:
                sync.change("orders", "update", key={"id": oid}, label={"customer": cid},
                            changes=changes, error=ValueError(
                                "deadlock detected while updating order %d (%s)" % (oid, g.token())))
            else:
                sync.change("orders", "update", key={"id": oid}, label={"customer": cid},
                            changes=changes, msg=g.text(2, 6) if r.random() < 0.3 else None)
            g.spend()
        elif op < 0.6:
            sync.change("orders", "delete", key={"id": oid}, label={"customer": cid},
                        msg="orphan order removed")
            g.spend()


def _line_change(g, sync, oid, line_no):
    r = g.r
    table = r.choice(TABLES[1:])
    key = {"order_id": oid, "line_no": line_no}
    if r.random() < 0.7:
        changes = {"qty": [r.randint(0, 9), r.randint(1, 20)], "price": [g.money(), g.money()]}
        if r.random() < 0.6:
            changes["description"] = [g.text(2, 6), g.text(2, 6)]
        sync.change(table, "update", key=key, label={"sku": g.token()}, changes=changes)
    elif r.random() < 0.5:
        sync.change(table, "insert", key=key, changes={"sku": g.token(), "qty": r.randint(1, 50)},
                    error=None if r.random() > 0.05 else KeyError("duplicate key " + g.token()))
    else:
        sync.debug("line %d unchanged" % line_no, fields=g.fields())
    g.spend()


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    generate(sys.argv[2], int(sys.argv[1]), int(sys.argv[3]) if len(sys.argv) > 3 else 0)
