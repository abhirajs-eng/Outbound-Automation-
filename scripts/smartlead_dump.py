#!/usr/bin/env python3
"""Dump every Smartlead campaign — settings, sequences, signatures — to disk.

Read-only. Makes no writes to the Smartlead account.

Usage:
    export SMARTLEAD_API_KEY=...
    python3 scripts/smartlead_dump.py [--out docs/smartlead-export]

Writes one JSON file per campaign plus a combined `_all.json`, so the
sequence bodies can be read directly and diffed between runs.
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

# Smartlead authenticates via an `api_key` query param only. Bearer and
# x-api-key headers are both rejected with "API key is required."
API_KEY = os.environ.get("SMARTLEAD_API_KEY")


def get(path, **params):
    """GET a Smartlead endpoint. Returns (data, error_message)."""
    params["api_key"] = API_KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    # Smartlead sits behind Cloudflare, which rejects urllib's default
    # user-agent outright (403, "error code: 1010"). Any ordinary UA passes.
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r), None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            # Plan/auth failures are terminal — retrying just burns time.
            if e.code in (401, 403):
                return None, f"HTTP {e.code}: {body}"
            if attempt == 3:
                return None, f"HTTP {e.code}: {body}"
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                return None, f"network: {e}"
        time.sleep(2 ** attempt)
    return None, "exhausted retries"


def dump_campaign(cid):
    """Pull every readable facet of one campaign."""
    out = {}
    for key, path in (
        ("settings", f"campaigns/{cid}"),
        ("sequences", f"campaigns/{cid}/sequences"),
        ("email_accounts", f"campaigns/{cid}/email-accounts"),
    ):
        data, err = get(path)
        out[key] = data if err is None else {"_error": err}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/smartlead-export")
    args = ap.parse_args()

    if not API_KEY:
        sys.exit("SMARTLEAD_API_KEY is not set")

    campaigns, err = get("campaigns")
    if err:
        sys.exit(
            f"could not list campaigns — {err}\n"
            "'Plan expired!' means the Smartlead subscription lapsed; the key "
            "itself is still valid but the API rejects reads until it renews."
        )

    os.makedirs(args.out, exist_ok=True)
    combined = []
    for c in campaigns:
        cid, name = c["id"], c.get("name", "")
        print(f"  {cid}  {name}")
        record = {"id": cid, "name": name, "list_entry": c, **dump_campaign(cid)}
        combined.append(record)
        slug = "".join(ch if ch.isalnum() else "-" for ch in name).strip("-").lower()
        with open(os.path.join(args.out, f"{cid}-{slug}.json"), "w") as f:
            json.dump(record, f, indent=2)

    with open(os.path.join(args.out, "_all.json"), "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n{len(combined)} campaign(s) -> {args.out}/")


if __name__ == "__main__":
    main()
