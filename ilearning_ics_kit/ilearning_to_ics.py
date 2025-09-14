#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iLearning -> ICS generator (Moodle-like)
----------------------------------------
Logs into an iLearning/Moodle-style site, visits each course's assignment index,
parses assignment titles + due dates, then emits a single ICS file you can subscribe to
from iPad/Apple Calendar (or any calendar).

Environment variables (required):
- ILEARNING_BASE_URL  e.g., https://ilearning.yourschool.edu
- ILEARNING_USERNAME
- ILEARNING_PASSWORD
- COURSE_IDS          comma-separated Moodle course IDs, e.g. "123,456,789"
Optional:
- TIMEZONE            default "Asia/Taipei"
- ICS_OUTPUT          default "public/ilearning.ics"

Notes:
- This script targets Moodle-like HTML tables at /mod/assign/index.php?id=<course_id>
  with columns [Course, Assignment, Due date, Submitted]. Many schools' iLearning 3.0
  are Moodle-based and expose this view. If your HTML is different, adjust the selectors
  in parse_assign_table().
- For quizzes, forums, etc., you can add more fetchers by copying parse_assign_table()
  and pointing to relevant module index pages.
"""

import os, re, sys, hashlib
from datetime import datetime, timedelta
from urllib.parse import urljoin
from dateutil import parser as dtparser, tz
import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event, DisplayAlarm

def env(name, default=None, required=False):
    val = os.getenv(name, default)
    if required and (val is None or str(val).strip() == ""):
        print(f"[ERROR] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    return val

BASE = env("ILEARNING_BASE_URL", required=True).rstrip("/")
USERNAME = env("ILEARNING_USERNAME", required=True)
PASSWORD = env("ILEARNING_PASSWORD", required=True)
COURSE_IDS = [s.strip() for s in env("COURSE_IDS", required=True).split(",") if s.strip()]
TZNAME = env("TIMEZONE", "Asia/Taipei")
ICS_OUTPUT = env("ICS_OUTPUT", "public/ilearning.ics")

LOCAL_TZ = tz.gettz(TZNAME)
if LOCAL_TZ is None:
    print(f"[WARN] Unknown timezone '{TZNAME}', falling back to Asia/Taipei")
    LOCAL_TZ = tz.gettz("Asia/Taipei")

sess = requests.Session()
sess.headers.update({"User-Agent": "iLearning-ICS/1.0 (+github.com)"})
sess.cookies.set("MOODLEID", "1")  # harmless cookie to mimic browser a bit

def login():
    # Basic Moodle form login. If your school uses SSO/IdP, you may need to
    # adapt this to follow redirects and post through the IdP login form.
    login_url = urljoin(BASE, "/login/index.php")
    r = sess.get(login_url, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form", {"id": "login"})
    if not form:
        # Some themes don't label id="login". Try generic login form.
        forms = soup.find_all("form")
        form = forms[0] if forms else None
    if not form:
        print("[WARN] Could not locate login form. Trying direct POST...")
        form_action = login_url
    else:
        form_action = urljoin(login_url, form.get("action") or "")

    payload = {}
    # Common Moodle login fields
    payload["username"] = USERNAME
    payload["password"] = PASSWORD
    # Some sites require additional hidden fields; include all hidden inputs.
    if form:
        for inp in form.find_all("input", {"type": "hidden"}):
            payload[inp.get("name","")] = inp.get("value","")

    rr = sess.post(form_action, data=payload, allow_redirects=True)
    rr.raise_for_status()
    # A crude success check: presence of "logout" link or absence of "loginerrormessage"
    if "loginerrormessage" in rr.text.lower() or "invalid login" in rr.text.lower():
        print("[ERROR] Login appears to have failed. Check credentials.", file=sys.stderr)
        sys.exit(2)
    return True

def parse_assign_table(html, course_id):
    """Return list of dict: {title, due_at (aware datetime), url, course_id}"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    events = []
    if not table:
        return events

    # Try to locate rows with an <a> to the assignment and a cell containing due date
    for tr in table.find_all("tr"):
        a = tr.find("a", href=True)
        if not a or "mod/assign" not in a["href"]:
            continue
        title = a.get_text(strip=True)
        # Heuristics to find due-date cell: look for 'due' keyword or a date-looking string
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        # Join to search, but prefer later cells
        due_text = ""
        for td_text in reversed(tds):
            if re.search(r"(due|截止|繳交|期限|到期)", td_text, re.I):
                due_text = td_text
                break
        if not due_text:
            # Fallback: find first date-ish token in row
            m = re.search(r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}([ T]\d{1,2}:\d{2})?)", " ".join(tds))
            if m:
                due_text = m.group(1)
        if not due_text:
            continue

        # Clean typical prefixes like "Due date Friday, 20 September 2025, 23:59"
        due_text = re.sub(r"^(Due date|截止|繳交期限|到期)[:：]?\s*", "", due_text, flags=re.I)

        # Parse with dateutil; assume local tz if naive
        try:
            dt = dtparser.parse(due_text, dayfirst=False, fuzzy=True)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        else:
            dt = dt.astimezone(LOCAL_TZ)

        url = urljoin(BASE + "/", a["href"].lstrip("/"))
        events.append({
            "title": title,
            "due_at": dt,
            "url": url,
            "course_id": course_id
        })
    return events

def fetch_course_assignments(course_id):
    url = urljoin(BASE, f"/mod/assign/index.php?id={course_id}")
    r = sess.get(url, allow_redirects=True)
    r.raise_for_status()
    return parse_assign_table(r.text, course_id)

def stable_uid(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest() + "@ilearning-ics"

def build_calendar(events):
    cal = Calendar()
    now = datetime.now(tz=LOCAL_TZ)
    for ev in events:
        e = Event()
        e.name = f"[iLearning] {ev['title']}"
        e.begin = ev["due_at"]
        e.end = ev["due_at"]  # due-time as instant; iOS shows at exact time
        e.created = now
        e.last_modified = now
        e.url = ev["url"]
        e.description = f"來源: {ev['url']}\\n課程ID: {ev['course_id']}"
        e.uid = stable_uid(ev["url"] + ev["title"])
        # Reminders: 1 day & 3 hours before
        e.alarms = [
            DisplayAlarm(trigger=timedelta(days=-1)),
            DisplayAlarm(trigger=timedelta(hours=-3)),
        ]
        cal.events.add(e)
    return cal

def main():
    print("[iLearning-ICS] Logging in...")
    login()
    all_events = []
    for cid in COURSE_IDS:
        try:
            print(f"[iLearning-ICS] Fetching course {cid} assignments...")
            evs = fetch_course_assignments(cid)
            print(f"  -> {len(evs)} assignments")
            all_events.extend(evs)
        except Exception as e:
            print(f"[WARN] Failed course {cid}: {e}")

    cal = build_calendar(all_events)
    out_path = ICS_OUTPUT
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(cal)
    print(f"[iLearning-ICS] Wrote {out_path} with {len(all_events)} events.")

if __name__ == "__main__":
    main()
