"""
RTL Word Collator
==================
Pulls responses from the "RTL word collator" Google Sheet, splits each
response into word/count lines, spellchecks and flags near-identical
spellings for you to confirm, then shows the collated totals. Can also
reset (clear) the response rows so the next workshop round starts from
zero.

This module holds the core logic. It is used by:
  - streamlit_app.py   the hosted web app (Streamlit)
  - this file's CLI    python word_collator.py [check|reset]

CONFIGURATION
-------------
Settings are read from environment variables, or from Streamlit secrets
(.streamlit/secrets.toml locally, the "Secrets" box on Streamlit Cloud):

    SPREADSHEET_ID           ID of the "RTL word collator (Responses)" sheet
    GOOGLE_TOKEN_JSON        contents of token.json (must include refresh_token)
    GOOGLE_CREDENTIALS_JSON  contents of credentials.json (OAuth client)

For local CLI use, token.json / credentials.json next to this file still
work as a fallback, and the browser sign-in flow runs if no token exists.

NOTE ON RESET
-------------
This clears the rows in the linked Sheet, which is what "check" reads
from -- that's a full reset for this tool's purposes. It does not
delete the response count shown inside the Google Forms UI itself;
if you also want that cleared, do Responses -> the three-dot menu ->
"Delete all responses" in the Forms editor as well.
"""

import json
import os
import re
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from spellchecker import SpellChecker

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_TAB = "Form Responses 1"
DATA_RANGE = f"{SHEET_TAB}!A:B"
RESET_RANGE = f"{SHEET_TAB}!A2:B"

TOKEN_FILE = Path(__file__).with_name("token.json")
CREDS_FILE = Path(__file__).with_name("credentials.json")

spell = SpellChecker()


class ConfigError(RuntimeError):
    pass


def get_setting(name):
    """Look up a setting in the environment first, then Streamlit secrets."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return None


def _as_dict(value):
    """Secrets may be a JSON string or (in secrets.toml) a table."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def get_spreadsheet_id():
    sheet_id = get_setting("SPREADSHEET_ID")
    if not sheet_id:
        raise ConfigError("SPREADSHEET_ID is not set.")
    return sheet_id


def load_credentials(allow_browser_flow=False):
    token_info = _as_dict(get_setting("GOOGLE_TOKEN_JSON"))
    client_info = _as_dict(get_setting("GOOGLE_CREDENTIALS_JSON"))

    if token_info is None and TOKEN_FILE.exists():
        token_info = json.loads(TOKEN_FILE.read_text())
    if client_info is None and CREDS_FILE.exists():
        client_info = json.loads(CREDS_FILE.read_text())

    creds = None
    if token_info:
        # token.json normally carries client_id/secret already; fill them
        # in from credentials.json if they're missing.
        if client_info and not token_info.get("client_id"):
            client = client_info.get("installed") or client_info.get("web") or {}
            token_info.setdefault("client_id", client.get("client_id"))
            token_info.setdefault("client_secret", client.get("client_secret"))
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if creds and creds.valid:
        return creds
    if creds and creds.refresh_token:
        creds.refresh(Request())
        return creds

    if not allow_browser_flow:
        raise ConfigError(
            "No usable Google token. Set GOOGLE_TOKEN_JSON to the contents "
            "of a token.json that includes a refresh_token."
        )
    if not client_info:
        raise ConfigError(
            "No OAuth client found. Set GOOGLE_CREDENTIALS_JSON or put "
            "credentials.json next to this script."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(client_info, SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def get_service(allow_browser_flow=False):
    creds = load_credentials(allow_browser_flow)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_rows(service):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=get_spreadsheet_id(), range=DATA_RANGE)
        .execute()
    )
    return result.get("values", [])


def clear_rows(service):
    service.spreadsheets().values().clear(
        spreadsheetId=get_spreadsheet_id(), range=RESET_RANGE
    ).execute()


def parse_lines(cell_text):
    """Split one response cell into (word, count) pairs. A line with no
    trailing number is treated as count 1."""
    entries = []
    for line in cell_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.*\S)\s+(\d+)\s*$", line)
        if m:
            word, count = m.group(1), int(m.group(2))
        else:
            word, count = line, 1
        word = re.sub(r"[:\-–—]+$", "", word).strip()
        if word:
            entries.append((word, count))
    return entries


def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (ca != cb),
            )
        prev = cur
    return prev[-1]


def correctly_spelled(word):
    return word.lower() in spell


def pick_correct(label_a, label_b):
    """Return the correctly-spelled label if exactly one of the two
    checks out against the English dictionary, else None (defer to
    the person)."""
    a_ok, b_ok = correctly_spelled(label_a), correctly_spelled(label_b)
    if a_ok and not b_ok:
        return label_a
    if b_ok and not a_ok:
        return label_b
    return None


def collate(rows, decide):
    """Collate responses into sorted (word, count) pairs.

    `decide(pair)` is called for each near-identical spelling pair and
    must return True (same word, merge) or False (different words).
    `pair` is a dict with keys: key, label_a, count_a, label_b, count_b,
    suggestion.
    """
    raw = []
    for row in rows[1:]:  # skip header row
        if len(row) < 2:
            continue
        raw.extend(parse_lines(row[1]))

    groups = {}  # norm -> {"count": int, "variants": {display_text: count}}
    for word, count in raw:
        norm = re.sub(r"\s+", " ", word.lower()).strip()
        g = groups.setdefault(norm, {"count": 0, "variants": {}})
        g["count"] += count
        g["variants"][word] = g["variants"].get(word, 0) + count

    norms = list(groups.keys())
    merged_into = {}

    for i in range(len(norms)):
        for j in range(i + 1, len(norms)):
            a, b = norms[i], norms[j]
            if a in merged_into or b in merged_into:
                continue
            max_len = max(len(a), len(b))
            threshold = 1 if max_len <= 4 else (2 if max_len <= 7 else 3)
            dist = levenshtein(a, b)
            if not (0 < dist <= threshold):
                continue

            label_a = max(groups[a]["variants"], key=groups[a]["variants"].get)
            label_b = max(groups[b]["variants"], key=groups[b]["variants"].get)
            suggestion = pick_correct(label_a, label_b)

            same = decide({
                "key": "|".join(sorted((a, b))),
                "label_a": label_a,
                "count_a": groups[a]["count"],
                "label_b": label_b,
                "count_b": groups[b]["count"],
                "suggestion": suggestion,
            })

            if same:
                canonical, other = a, b
                if suggestion == label_b:
                    canonical, other = b, a
                groups[canonical]["count"] += groups[other]["count"]
                for v, c in groups[other]["variants"].items():
                    groups[canonical]["variants"][v] = groups[canonical]["variants"].get(v, 0) + c
                if suggestion:
                    # keep only the correctly-spelled label going forward
                    groups[canonical]["variants"] = {suggestion: groups[canonical]["count"]}
                merged_into[other] = canonical

    results = []
    for norm, g in groups.items():
        if norm in merged_into:
            continue
        display = max(g["variants"], key=g["variants"].get)
        display = display[0].upper() + display[1:]
        results.append((display, g["count"]))
    results.sort(key=lambda x: x[0].lower())
    return results


# ---------------------------------------------------------------- CLI --


def _ask_in_terminal(pair):
    prompt = f'"{pair["label_a"]}" ({pair["count_a"]}) vs "{pair["label_b"]}" ({pair["count_b"]})'
    if pair["suggestion"]:
        prompt += f' -- spellcheck says "{pair["suggestion"]}" is correct'
    return input(f"{prompt}. Same word? [y/n] ").strip().lower() == "y"


def cmd_check():
    service = get_service(allow_browser_flow=True)
    rows = fetch_rows(service)
    if len(rows) <= 1:
        print("No responses yet.")
        return
    results = collate(rows, _ask_in_terminal)
    print()
    for word, count in results:
        print(f"{word} ({count})")


def cmd_reset():
    service = get_service(allow_browser_flow=True)
    confirm = input(
        "This clears all response rows from the Sheet (the form itself "
        "and its questions stay intact, and it keeps accepting new "
        "submissions). Continue? [y/n] "
    ).strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return
    clear_rows(service)
    print("Cleared. Ready for the next round.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "reset"):
        print("Usage: python word_collator.py [check|reset]")
        sys.exit(1)
    try:
        if sys.argv[1] == "check":
            cmd_check()
        else:
            cmd_reset()
    except ConfigError as e:
        sys.exit(str(e))
