#!/usr/bin/env python3
"""Create a Smartlead campaign from a sequence spec (see docs/sequences/*.json).

Applies the house conventions read off the existing FINAL Qualifiers campaigns
(documented in docs/smartlead-account-notes.md):

  - schedule: America/Los_Angeles, weekdays, 09:30-11:30, 10 leads/day,
    10 min between emails, stop on reply, follow-ups to 100%
  - bodies are <p> tags only, signature via the %signature% token
  - open and click tracking are DISABLED, unlike the existing campaigns

That last one is a deliberate divergence. Click tracking rewrites every link
through a Smartlead tracking domain, so an App Store link stops resolving to
apple.com in the raw HTML -- a real spam-filter risk at 10 sends/day.

The campaign is left in DRAFTED status. This script never starts a campaign.

    python3 scripts/smartlead_create_campaign.py docs/sequences/sequence-1.json
    python3 scripts/smartlead_create_campaign.py <spec> --dry-run
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://server.smartlead.ai/api/v1"
API_KEY = os.environ.get("SMARTLEAD_API_KEY")
UA = {"User-Agent": "curl/8.5.0", "Content-Type": "application/json"}

SCHEDULE = {
    "timezone": "America/Los_Angeles",
    "days_of_the_week": [1, 2, 3, 4, 5],
    "start_hour": "09:30",
    "end_hour": "11:30",
    "min_time_btw_emails": 10,
    "max_new_leads_per_day": 10,
}
SETTINGS = {
    "track_settings": ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],
    "stop_lead_settings": "REPLY_TO_AN_EMAIL",
    "send_as_plain_text": False,
    "follow_up_percentage": 100,
}


def call(method, path, body=None, **params):
    params["api_key"] = API_KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=UA, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r), None
        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code in (400, 401, 403, 422) or attempt == 3:
                return None, msg
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                return None, f"network: {e}"
        time.sleep(2 ** attempt)
    return None, "exhausted retries"


def die(step, err):
    sys.exit(f"\n  FAILED at {step}\n  {err}")


def html(paragraphs):
    """House format: <p> tags only, straight quotes, no em-dashes."""
    out = "".join(f"<p>{p}</p>" for p in paragraphs)
    return out.replace("’", "'").replace("‘", "'") \
              .replace("“", '"').replace("”", '"') \
              .replace("—", ", ").replace("–", "-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--campaign-id", type=int,
                    help="configure this existing campaign instead of creating "
                         "one; use to resume after a partial failure")
    args = ap.parse_args()

    if not API_KEY:
        sys.exit("SMARTLEAD_API_KEY is not set")

    spec = json.load(open(args.spec))
    steps = sorted(spec["steps"], key=lambda s: s["seq_number"])
    sequences = [
        {
            "seq_number": s["seq_number"],
            # The write API wants snake_case here even though the read API
            # hands back delayInDays. Not a typo.
            "seq_delay_details": {"delay_in_days": s["delay_days"]},
            "subject": s["subject"],
            "email_body": html(s["body"]),
        }
        for s in steps
    ]

    if args.dry_run:
        print(json.dumps({"schedule": SCHEDULE, "settings": SETTINGS,
                          "sequences": sequences}, indent=2))
        return

    # 1. leads first -- if the source campaign can't be read, nothing is created
    leads = []
    src = spec.get("copy_leads_from_campaign")
    if src:
        data, err = call("GET", f"campaigns/{src}/leads", offset=0, limit=100)
        if err:
            die("reading source leads", err)
        for entry in data.get("data", []):
            l = entry["lead"]
            leads.append({k: l[k] for k in (
                "first_name", "last_name", "email", "company_name",
                "website", "location", "phone_number", "linkedin_profile",
                "company_url", "custom_fields") if l.get(k)})
        print(f"  leads read from {src}: {len(leads)}")

    # 2. resolve the sending mailbox and make sure %signature% has something
    #    to resolve to -- 15 of 18 mailboxes have a null signature.
    mailbox_id = None
    if spec.get("sending_mailbox"):
        accounts, err = call("GET", "email-accounts", offset=0, limit=100)
        if err:
            die("listing mailboxes", err)
        match = [a for a in accounts
                 if a["from_email"].lower() == spec["sending_mailbox"].lower()]
        if not match:
            die("resolving mailbox", f"{spec['sending_mailbox']} not connected")
        mailbox_id = match[0]["id"]
        want = spec.get("mailbox_signature")
        if want and match[0].get("signature") != want:
            _, err = call("POST", f"email-accounts/{mailbox_id}",
                          {"signature": want})
            if err:
                die("setting mailbox signature", err)
            print(f"  signature set on {spec['sending_mailbox']}: {want!r}")

    # 3. create, then configure
    if args.campaign_id:
        cid = args.campaign_id
        print(f"  reusing existing campaign: {cid}")
    else:
        created, err = call("POST", "campaigns/create",
                            {"name": spec["campaign_name"]})
        if err:
            die("creating campaign", err)
        cid = created.get("id")
        print(f"  campaign created: {cid}  {spec['campaign_name']}")

    for label, path, body in (
        ("schedule", f"campaigns/{cid}/schedule", SCHEDULE),
        ("settings", f"campaigns/{cid}/settings", SETTINGS),
        ("sequences", f"campaigns/{cid}/sequences", {"sequences": sequences}),
    ):
        _, err = call("POST", path, body)
        if err:
            die(f"{label} (campaign {cid} was created -- delete or finish it)", err)
        print(f"  {label} applied")

    if mailbox_id:
        _, err = call("POST", f"campaigns/{cid}/email-accounts",
                      {"email_account_ids": [mailbox_id]})
        if err:
            die(f"attaching mailbox (campaign {cid} exists)", err)
        print(f"  mailbox attached: {spec['sending_mailbox']}")

    if leads:
        res, err = call("POST", f"campaigns/{cid}/leads", {"lead_list": leads})
        if err:
            die(f"adding leads (campaign {cid} exists)", err)
        print(f"  leads added: {res.get('upload_count', len(leads))}")

    print(f"\nDone. Campaign {cid} is DRAFTED and will not send until started.")


if __name__ == "__main__":
    main()
