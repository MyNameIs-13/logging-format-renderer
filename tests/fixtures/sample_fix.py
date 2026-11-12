"""A sample check/fix script, as a script author would write one with dbfixlog.

It works on a small SQLite shop database (created and seeded on first use):

1. orphan-check: orders whose customer is gone get a Finding and are deleted.
2. normalize: per customer, a missing email is a Finding, and lower-case order refs are
   upper-cased. One of those collides with an existing ref, so in a Write Run the UPDATE
   fails with IntegrityError and is logged as a failed Change; the script carries on.

    python3 sample_fix.py DB LOG [--write]

Without --write it is a Dry Run: everything is logged as planned and nothing is changed.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import dbfixlog  # noqa: E402

SEED = """
create table customers (id integer primary key, name text not null, email text);
create table orders (id integer primary key, customer_id integer not null,
                     ref text not null unique, status text not null);
insert into customers values (1, 'ACME', 'buy@acme.example'), (2, 'Bolt BV', null),
                             (3, 'Cora & Co', 'hi@cora.example'), (4, 'Dyn', 'x@dyn.example');
insert into orders values (10, 1, 'a-10', 'open'), (11, 1, 'A-11', 'paid'),
                          (12, 2, 'b-12', 'open'), (13, 3, 'C-13', 'shipped'),
                          (14, 3, 'a-11', 'open'), (20, 99, 'Z-20', 'open'),
                          (21, 98, 'Z-21', 'paid');
"""


def connect(path):
    fresh = not os.path.exists(path)
    con = sqlite3.connect(path)
    if fresh:
        con.executescript(SEED)
    return con


@dbfixlog.scope("phase", label={"name": "orphan-check"}, msg="orders without a customer")
def orphan_check(con, log):
    rows = con.execute("select o.id, o.ref, o.customer_id from orders o left join customers c"
                       " on c.id = o.customer_id where c.id is null order by o.id").fetchall()
    log.info("found %d orphan orders", len(rows), fields={"count": len(rows)})
    for oid, ref, cid in rows:
        log.finding("orphan-order", "customer %d does not exist" % cid, table="orders",
                    key={"id": oid}, label={"ref": ref})
        if log.write_run:
            con.execute("delete from orders where id = ?", (oid,))
        log.change("orders", "delete", key={"id": oid}, label={"ref": ref},
                   msg="orphan order removed")


@dbfixlog.scope("phase", label={"name": "normalize"}, msg="customer data and order refs")
def normalize(con, log):
    for cid, name, email in con.execute("select id, name, email from customers order by id").fetchall():
        with log.scope("customer", key={"id": cid}, label={"name": name}):
            if not email:
                log.finding("missing-email", table="customers", key={"id": cid},
                            label={"name": name})
            orders = con.execute("select id, ref from orders where customer_id = ? order by id",
                                 (cid,)).fetchall()
            log.debug("%d orders", len(orders), fields={"ids": [o[0] for o in orders]})
            for oid, ref in orders:
                if ref == ref.upper():
                    continue
                with log.scope("order", key={"id": oid}, label={"ref": ref}):
                    fix_ref(con, log, oid, ref)


def fix_ref(con, log, oid, ref):
    new = ref.upper()
    change = dict(key={"id": oid}, label={"ref": ref}, changes={"ref": (ref, new)})
    if log.dry_run:
        log.change("orders", "update", **change)
        return
    try:
        con.execute("update orders set ref = ? where id = ?", (new, oid))
    except sqlite3.IntegrityError as e:
        log.change("orders", "update", error=e, **change)
    else:
        log.change("orders", "update", **change)


def main(argv):
    db, path = argv[1], argv[2]
    write = "--write" in argv[3:]
    con = connect(db)
    with dbfixlog.run(path, mode="write" if write else "dry", overwrite=True,
                      title="Orphaned orders and order refs", description="sample_fix.py",
                      target={"database": os.path.basename(db)},
                      fields={"ticket": "SHOP-42"}) as log:
        log.info("connected", fields={"database": db})
        orphan_check(con, log)
        normalize(con, log)
        if write:
            con.commit()
            log.info("committed")
    con.close()


if __name__ == "__main__":
    main(sys.argv)
