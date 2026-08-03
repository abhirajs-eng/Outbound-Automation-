#!/usr/bin/env python3
"""Split one lead batch across the three sequence arms and create the campaigns.

    python3 scripts/smartlead_launch_batch.py --leads leads.csv --suffix "Aug batch"
    python3 scripts/smartlead_launch_batch.py --leads leads.csv --dry-run

Accepts CSV (header row) or JSON (list of objects). Column names are matched
loosely, so an Apollo or HubSpot export usually works untouched:

    email          <- email, work_email, email_address
    first_name     <- first_name, firstname, "First Name"
    last_name      <- last_name, lastname, "Last Name"
    company_name   <- company, company_name, organization_name, account_name
    website        <- website, company_url, domain
    location       <- location, city, formatted_address

Leads are split ROUND-ROBIN, not into contiguous chunks. Exports usually arrive
sorted by score, company size or import order, so slicing the file into thirds
would hand one arm all the best prospects and make the arms incomparable.
Round-robin keeps the three arms statistically alike, which is the entire point
of running three message variants against one list.

Campaigns are created DRAFTED. This script never starts one.
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://server.smartlead.ai/api/v1"
API_KEY = os.environ.get("SMARTLEAD_API_KEY")
UA = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}

SPECS = ["docs/sequences/sequence-1.json",
         "docs/sequences/sequence-2.json",
         "docs/sequences/sequence-3.json"]

# Warmed but deliberately held back until warmup is further along.
EXCLUDE_MAILBOXES = {"harsh@audriahq.com", "sneha@getaudria.com"}

ALIASES = {
    "email": ("email", "work_email", "email_address", "primary_email"),
    "first_name": ("first_name", "firstname", "first name", "given_name"),
    "last_name": ("last_name", "lastname", "last name", "family_name"),
    "company_name": ("company_name", "company", "organization_name",
                     "account_name", "organization"),
    "website": ("website", "company_url", "domain", "company_domain",
                "website_url"),
    "location": ("location", "city", "formatted_address", "address"),
    "phone_number": ("phone_number", "phone", "work_direct_phone"),
    "linkedin_profile": ("linkedin_profile", "linkedin_url", "linkedin"),
}


def call(method, path, body=None, **params):
    params["api_key"] = API_KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=UA, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:250]}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"network: {e}"


def normalise(row):
    """Map one export row onto Smartlead's lead fields."""
    low = {str(k).strip().lower(): v for k, v in row.items() if k}
    out = {}
    for field, names in ALIASES.items():
        for n in names:
            v = low.get(n)
            if v not in (None, "", "null"):
                out[field] = str(v).strip()
                break
    return out


def load_leads(path):
    raw = open(path, encoding="utf-8-sig").read()
    if path.lower().endswith(".json"):
        rows = json.loads(raw)
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
    else:
        rows = list(csv.DictReader(io.StringIO(raw)))

    leads, seen, skipped = [], set(), 0
    for r in rows:
        l = normalise(r)
        e = l.get("email", "").lower()
        if not e or "@" not in e or e in seen:
            skipped += 1
            continue
        seen.add(e)
        leads.append(l)
    return leads, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leads", required=True, help="CSV or JSON export")
    ap.add_argument("--suffix", default="", help="appended to campaign names")
    ap.add_argument("--leads-per-day", type=int, default=25,
                    help="new leads entering EACH campaign per day (default 25)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not API_KEY and not args.dry_run:
        sys.exit("SMARTLEAD_API_KEY is not set")

    leads, skipped = load_leads(args.leads)
    if not leads:
        sys.exit(f"no usable leads in {args.leads}")

    # Round-robin so the three arms stay comparable. See module docstring.
    arms = [leads[i::3] for i in range(3)]
    print(f"  {len(leads)} unique leads ({skipped} skipped: blank/dupe/no email)")
    print(f"  split -> {[len(a) for a in arms]}\n")

    if args.dry_run:
        for spec, arm in zip(SPECS, arms):
            name = json.load(open(spec))["campaign_name"]
            print(f"  {name}: {len(arm)} leads")
            for l in arm[:3]:
                print(f"      {l.get('first_name','')} <{l['email']}> "
                      f"{l.get('company_name','')}")
            if len(arm) > 3:
                print(f"      ... and {len(arm)-3} more")
        return

    accounts, err = call("GET", "email-accounts", offset=0, limit=100)
    if err:
        sys.exit(f"could not list mailboxes: {err}")
    pool = [a["id"] for a in accounts
            if a["from_email"].lower() not in EXCLUDE_MAILBOXES]
    missing = [a["from_email"] for a in accounts
               if a["id"] in pool and not a.get("signature")]
    if missing:
        sys.exit(f"these mailboxes have no signature, %signature% would break: "
                 f"{missing}")
    print(f"  mailbox pool: {len(pool)}\n")

    created = []
    for spec, arm in zip(SPECS, arms):
        s = json.load(open(spec))
        name = s["campaign_name"] + (f" - {args.suffix}" if args.suffix else "")

        # Reuse the proven creator for schedule/settings/sequences, then
        # attach this arm's leads and the full mailbox pool.
        r = subprocess.run(
            [sys.executable, "scripts/smartlead_create_campaign.py", spec],
            capture_output=True, text=True)
        print(r.stdout.rstrip())
        if r.returncode != 0:
            sys.exit(f"creating {name} failed:\n{r.stdout}\n{r.stderr}")
        cid = int([l for l in r.stdout.splitlines()
                   if "campaign created:" in l][0].split()[2])

        call("POST", f"campaigns/{cid}", {"name": name})
        call("POST", f"campaigns/{cid}/schedule",
             {"timezone": "America/Los_Angeles", "days_of_the_week": [1,2,3,4,5],
              "start_hour": "09:30", "end_hour": "11:30",
              "min_time_btw_emails": 10,
              "max_new_leads_per_day": args.leads_per_day})
        _, err = call("POST", f"campaigns/{cid}/email-accounts",
                      {"email_account_ids": pool})
        if err:
            sys.exit(f"attaching mailboxes to {cid}: {err}")
        _, err = call("POST", f"campaigns/{cid}/leads", {"lead_list": arm})
        if err:
            sys.exit(f"adding leads to {cid}: {err}")
        created.append((cid, name, len(arm)))
        print(f"  -> {cid}  {name}  {len(arm)} leads, {len(pool)} mailboxes\n")

    print("Created (all DRAFTED, none will send until started):")
    for cid, name, n in created:
        print(f"  {cid}  {name:<34} {n} leads")


if __name__ == "__main__":
    main()
