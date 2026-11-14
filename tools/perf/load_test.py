"""Load test for BuildCore web: N people working at the same time, each signed in on their own.

    python tools/perf/load_test.py --base https://your-staging.vercel.app --company main --company-password ... \
        --user loadtest --password ... --users 1,10,25,50 --seconds 60

Use a STAGING copy (a Vercel preview deployment on a Supabase copy), never the live company: the script signs in and
switches workspace, which writes session rows. Only the Python standard library is needed.

Each simulated person repeats what a person does on an ordinary screen: who am I, the lists, approvals, the live
activity check, the Command centre's cash summary, and one small write (entering the company workspace). It prints,
per number of people: requests per second, average / p95 / p99 response time, the error rate, and the slowest calls.
"""
import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request

MIX = [("auth.me", {}, 3), ("lookups", {}, 2), ("dash.approvals", {}, 2), ("team.tick", {"since_id": 0}, 6),
       ("cm.unread", {}, 2), ("cash.summary", {}, 1), ("ws.enter", {"workspace": "company"}, 1)]


def post(base, fn, args, headers, timeout):
    body = json.dumps({"fn": fn, "args": args}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/api", data=body, method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **headers))
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read())
        ok = bool(j.get("ok"))
        err = None if ok else str(j.get("error"))[:80]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        j, ok, err = None, False, type(e).__name__
    return (time.perf_counter() - t) * 1000, ok, err, j


def sign_in(a):
    hd = {"X-Company": a.company}
    _, ok, err, j = post(a.base, "co.gate_login", {"company_id": a.company, "password": a.company_password}, hd, 60)
    if not ok:
        raise SystemExit("Company sign-in failed: %s" % err)
    hd["X-Company-Ticket"] = j["data"]["ticket"]
    _, ok, err, j = post(a.base, "auth.login", {"username": a.user, "password": a.password}, hd, 60)
    if not ok:
        raise SystemExit("User sign-in failed: %s" % err)
    hd["X-Token"] = j["data"]["token"]
    return hd


def person(a, hd, stop, out, lock):
    bag = [(fn, args) for fn, args, w in MIX for _ in range(w)]
    while not stop.is_set():
        fn, args = random.choice(bag)
        ms, ok, err, _ = post(a.base, fn, args, hd, a.timeout)
        with lock:
            out.append((fn, ms, ok, err))
        time.sleep(random.uniform(0, a.think))


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))] if xs else 0


def run(a, n, sessions):
    out, lock, stop = [], threading.Lock(), threading.Event()
    th = [threading.Thread(target=person, args=(a, sessions[i % len(sessions)], stop, out, lock), daemon=True) for i in range(n)]
    t0 = time.perf_counter()
    for t in th:
        t.start()
    time.sleep(a.seconds)
    stop.set()
    for t in th:
        t.join(a.timeout + 5)
    dur = time.perf_counter() - t0
    ms = [x[1] for x in out]
    errs = [x for x in out if not x[2]]
    by = {}
    for fn, m, ok, _ in out:
        by.setdefault(fn, []).append(m)
    return {"users": n, "requests": len(out), "rps": round(len(out) / dur, 1),
            "avg_ms": round(statistics.mean(ms), 1) if ms else None, "p95_ms": round(pct(ms, 95), 1),
            "p99_ms": round(pct(ms, 99), 1), "error_rate_pct": round(100.0 * len(errs) / max(1, len(out)), 2),
            "errors": sorted({e[3] for e in errs})[:5],
            "per_call_p95_ms": {k: round(pct(v, 95), 1) for k, v in sorted(by.items())}}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True)
    p.add_argument("--company", default="main")
    p.add_argument("--company-password", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--users", default="1,10,25,50")
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--think", type=float, default=1.0, help="up to this many seconds between one person's requests")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--json", help="also write the results to this file")
    a = p.parse_args()
    levels = [int(x) for x in a.users.split(",")]
    sessions = [sign_in(a) for _ in range(max(levels))]
    results = []
    for n in levels:
        r = run(a, n, sessions)
        results.append(r)
        print("%3d people: %6.1f req/s  avg %7.1f ms  p95 %7.1f ms  p99 %7.1f ms  errors %5.2f%%  %s" % (
            n, r["rps"], r["avg_ms"] or 0, r["p95_ms"], r["p99_ms"], r["error_rate_pct"], ", ".join(r["errors"])))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
