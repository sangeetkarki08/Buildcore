"""Company A must not reach company B. Checks over HTTP, the way a browser (or an attacker with a browser) would.

    python tests/company_isolation.py --base http://127.0.0.1:8760 --setup-key ... \
        --a-company main --a-company-password ... --a-user admin --a-password ...

Run it on a STAGING copy: it sets up a second company ("isotest-<random>") through the normal sign-up, with the
setup key. Each check prints PASS or FAIL; the exit code is the number of failures.
"""
import argparse
import json
import secrets
import sys
import urllib.request


def call(base, fn, args=None, **hd):
    headers = {"Content-Type": "application/json"}
    headers.update({k.replace("_", "-"): v for k, v in hd.items() if v})
    req = urllib.request.Request(base.rstrip("/") + "/api", data=json.dumps({"fn": fn, "args": args or {}}).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True)
    p.add_argument("--setup-key", required=True)
    p.add_argument("--a-company", default="main")
    p.add_argument("--a-company-password", required=True)
    p.add_argument("--a-user", required=True)
    p.add_argument("--a-password", required=True)
    a = p.parse_args()
    B = a.base
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        fails += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> " + str(detail)[:200]))

    # company A: company sign-in, then user sign-in
    ga = call(B, "co.gate_login", {"company_id": a.a_company, "password": a.a_company_password}, X_Company=a.a_company)
    assert ga["ok"], ga
    code_a, ticket_a = ga["data"]["code"], ga["data"]["ticket"]
    la = call(B, "auth.login", {"username": a.a_user, "password": a.a_password}, X_Company=code_a, X_Company_Ticket=ticket_a)
    assert la["ok"], la
    token_a = la["data"]["token"]

    # company B, set up through the public sign-up
    cid = "isotest-" + secrets.token_hex(3)
    pw = secrets.token_urlsafe(9)
    su = call(B, "co.signup", {"company_key": a.setup_key, "name": "Isolation test " + cid, "admin_name": "Iso Admin",
                               "username": "isoadmin", "password": pw, "company_id": cid, "company_password": pw})
    assert su["ok"], su
    gb = call(B, "co.gate_login", {"company_id": cid, "password": pw})
    assert gb["ok"], gb
    code_b, ticket_b = gb["data"]["code"], gb["data"]["ticket"]
    lb = call(B, "auth.login", {"username": "isoadmin", "password": pw}, X_Company=code_b, X_Company_Ticket=ticket_b)
    assert lb["ok"], lb
    token_b = lb["data"]["token"]

    r = call(B, "lookups", X_Company=code_a, X_Token=token_a, X_Company_Ticket=ticket_a)
    check("A reads its own company", r.get("ok"), r)
    r = call(B, "lookups", X_Company=code_b, X_Token=token_a)
    check("A's sign-in is refused in B (no ticket)", not r.get("ok"), r)
    r = call(B, "lookups", X_Company=code_b, X_Token=token_a, X_Company_Ticket=ticket_b)
    check("A's sign-in is refused in B (even with B's company ticket)", not r.get("ok"), r)
    r = call(B, "auth.me", X_Company=code_a, X_Token=token_b, X_Company_Ticket=ticket_a)
    check("B's sign-in is refused in A", not r.get("ok"), r)
    r = call(B, "auth.status", X_Company=code_a, X_Company_Ticket=ticket_b)
    check("B's company ticket does not open A", (not r.get("ok")) and r.get("error") == "COMPANY_LOGIN", r)
    r = call(B, "auth.login", {"username": a.a_user, "password": a.a_password}, X_Company=code_b, X_Company_Ticket=ticket_b)
    check("A's user name and password do not sign in to B", not r.get("ok"), r)
    r = call(B, "co.list", X_Company=code_b, X_Token=token_b, X_Company_Ticket=ticket_b)
    names = json.dumps(r.get("data"))
    check("B's company list does not show A", r.get("ok") and code_a not in names.replace(code_b, ""), r)
    ra = call(B, "lookups", X_Company=code_a, X_Token=token_a, X_Company_Ticket=ticket_a)["data"]
    rb = call(B, "lookups", X_Company=code_b, X_Token=token_b, X_Company_Ticket=ticket_b)["data"]
    a_users = {u.get("name") for u in ra.get("users", [])} - {None}
    b_users = {u.get("name") for u in rb.get("users", [])} - {None}
    check("B's lists hold none of A's users", bool(a_users) and bool(b_users) and not (a_users & b_users), (a_users, b_users))
    print("%d failure(s). Remove the test company '%s' afterwards (Administration > Companies)." % (fails, cid))
    sys.exit(fails)


if __name__ == "__main__":
    main()
