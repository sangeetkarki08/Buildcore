"""Count the database round trips BuildCore makes: at server start and for each call. Run it on a STAGING database.

    set DATABASE_URL=postgresql://...      (a staging copy, never the live company)
    python tools/perf/db_trips.py --user admin --password ... [--fn auth.me,lookups,cash.summary] [--sql cash.summary]

Round trips are what decide speed on the web: each one is a trip between Vercel and Supabase (1-3 ms in the same
region, 100-250 ms between regions). Multiply a count by your trip time to see what it costs. --sql prints the
statements of the named calls, grouped, to find repeated questions.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))

import psycopg  # noqa: E402

COUNT = {"n": 0, "sql": []}
_execute = psycopg.ClientCursor.execute


def _counted(self, query, *a, **k):
    COUNT["n"] += 1
    COUNT["sql"].append(str(query))
    return _execute(self, query, *a, **k)


psycopg.ClientCursor.execute = _counted


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--fn", default="auth.me,lookups,dash.approvals,team.tick,cm.unread,dash.summary,cash.summary")
    p.add_argument("--sql", default="", help="calls whose statements to print, comma separated")
    a = p.parse_args()
    t = time.perf_counter()
    from web import boot
    server = boot.start()
    out = {"server_start": {"trips": COUNT["n"], "seconds": round(time.perf_counter() - t, 2)}}
    try:
        token = server.call("auth.login", {"username": a.user, "password": a.password}, None)["token"]
    except Exception as e:  # noqa: BLE001
        print(json.dumps(out, indent=1))
        sys.exit("Sign-in failed (%s). Use a staging copy with an active licence and a real user." % e)
    show = set(filter(None, a.sql.split(",")))
    for fn in filter(None, a.fn.split(",")):
        args = {"since_id": 0} if fn == "team.tick" else {}
        COUNT["n"], COUNT["sql"] = 0, []
        t = time.perf_counter()
        try:
            server.call(fn, args, token)
            err = None
        except Exception as e:  # noqa: BLE001
            err = str(e)[:120]
        out[fn] = {"trips": COUNT["n"], "ms": round((time.perf_counter() - t) * 1000), "error": err}
        if fn in show:
            shapes = Counter(re.sub(r"\s+", " ", re.sub(r"'[^']*'|\b\d+\b", "?", s))[:140] for s in COUNT["sql"])
            out[fn]["statements"] = shapes.most_common(25)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
