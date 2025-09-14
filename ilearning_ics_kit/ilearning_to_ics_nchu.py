#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCHU iLearning 3.0 (ee-class) -> ICS generator
----------------------------------------------
Target pages like:
  https://lms2020.nchu.edu.tw/course/homework/<course_id>

Environment variables:
- ILEARNING_BASE_URL (required) e.g., https://lms2020.nchu.edu.tw
- ILEARNING_USERNAME (required)
- ILEARNING_PASSWORD (required)
- EECLASS_HOMEWORK_URLS (required) comma-separated list of course homework list urls.
  You can pass either absolute URLs or paths like /course/homework/58430
Optional:
- TIMEZONE (default Asia/Taipei)
- ICS_OUTPUT (default public/ilearning.ics)

Notes:
- This scraper looks for rows that contain a homework link and a due-date-ish text in the same row.
  It tries to match Chinese labels like 繳交期限/截止/到期 and generic date-time patterns.
- If your list page doesn't show due times (only visible inside homework content page),
  set DEEP_FETCH=1 to fetch each homework detail page and parse due time there.
"""

import os, re, sys, hashlib
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
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
HOMEWORK_URLS = [s.strip() for s in env("EECLASS_HOMEWORK_URLS", required=True).split(",") if s.strip()]
TZNAME = env("TIMEZONE", "Asia/Taipei")
ICS_OUTPUT = env("ICS_OUTPUT", "public/ilearning.ics")
DEEP_FETCH = env("DEEP_FETCH", "0") == "1"

LOCAL_TZ = tz.gettz(TZNAME) or tz.gettz("Asia/Taipei")

sess = requests.Session()
sess.headers.update({"User-Agent": "NCHU-eeclass-ICS/1.0 (+github.com)"})
sess.cookies.set("EECLASSID", "1")

def to_abs(url_or_path: str) -> str:
    if url_or_path.startswith("http"):
        return url_or_path
    return urljoin(BASE + "/", url_or_path.lstrip("/"))

def login():
    # ee-class 3.0 usually has a /login route; we reuse Moodle-like login logic
    login_url = urljoin(BASE, "/login")
    r = sess.get(login_url, allow_redirects=True)
    # some schools map to /login/index.php; try a few
    if r.status_code >= 400 or "form" not in r.text.lower():
        for path in ["/login/index.php", "/login.php"]:
            rr = sess.get(urljoin(BASE, path), allow_redirects=True)
            if rr.ok and ("form" in rr.text.lower() or "username" in rr.text.lower()):
                r = rr
                break

    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form")
    if not form:
        print("[WARN] Could not locate login form; attempting POST with common fields...")
        form_action = login_url
        hidden = {}
    else:
        form_action = urljoin(login_url, form.get("action") or "")
        hidden = {
            inp.get("name",""): inp.get("value","")
            for inp in form.find_all("input", {"type": "hidden"})
        }

    payload = {"username": USERNAME, "password": PASSWORD, **hidden}
    rr = sess.post(form_action, data=payload, allow_redirects=True)
    rr.raise_for_status()
    if "login" in rr.url and ("error" in rr.text.lower() or "invalid" in rr.text.lower()):
        print("[ERROR] Login appears to have failed. Check credentials.", file=sys.stderr)
        sys.exit(2)

def parse_due(text: str):
    # Clean typical prefixes and parse date
    txt = re.sub(r"(繳交期限|截止|到期|Due|截止時間)[:：]?\s*", "", text, flags=re.I)
    # Try several common formats first
    # Add a missing seconds if needed; rely on dateutil
    try:
        dt = dtparser.parse(txt, fuzzy=True, dayfirst=False)
        return dt
    except Exception:
        # Try to pull first date-ish token
        m = re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}(?:\s+\d{1,2}:\d{2})?", txt)
        if m:
            try:
                return dtparser.parse(m.group(0), fuzzy=True)
            except Exception:
                return None
    return None

def parse_list_page(html, list_url):
    soup = BeautifulSoup(html, "lxml")
    events = []
    # find rows with homework links
    rows = soup.select("table tr")
    for tr in rows:
        a = tr.find("a", href=True)
        if not a: 
            continue
        href = a["href"]
        if "/course/homework/content" not in href and "/homework/content" not in href:
            # still accept; some themes link directly to homework detail without /content
            if "/homework" not in href:
                continue
        title = a.get_text(strip=True)
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        row_text = " ".join(tds)
        # find due text
        due_text = None
        for td_text in tds[::-1]:
            if re.search(r"(繳交期限|截止|到期|Due)", td_text, re.I):
                due_text = td_text
                break
        if not due_text:
            # fallback scan entire row
            due_text = row_text
        dt = parse_due(due_text)
        detail_url = urljoin(list_url, href)
        events.append((title, dt, detail_url))
    return events

def parse_detail_due(html):
    soup = BeautifulSoup(html, "lxml")
    # Look for labels like 繳交期限/截止時間
    candidates = []
    for lbl in soup.find_all(text=re.compile(r"(繳交期限|截止|到期|Due)", re.I)):
        # take surrounding text
        block = lbl if isinstance(lbl, str) else lbl.get_text(" ", strip=True)
        parent_text = lbl.parent.get_text(" ", strip=True) if hasattr(lbl, "parent") else ""
        cand = (parent_text or block)
        candidates.append(cand)
    text = " ".join(candidates) if candidates else soup.get_text(" ", strip=True)
    return parse_due(text)

def build_calendar(events):
    from ics import Calendar, Event, DisplayAlarm
    cal = Calendar()
    now = datetime.now(tz=LOCAL_TZ)
    for e in events:
        title, due_at, url = e
        if not due_at:
            # skip items without a parseable due date
            continue
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=LOCAL_TZ)
        else:
            due_at = due_at.astimezone(LOCAL_TZ)
        ev = Event()
        ev.name = f"[iLearning] {title}"
        ev.begin = due_at
        ev.end = due_at
        ev.created = now
        ev.last_modified = now
        ev.url = url
        ev.description = f"來源: {url}"
        ev.uid = hashlib.sha1((url + title).encode("utf-8")).hexdigest() + "@eeclass-ics"
        ev.alarms = [DisplayAlarm(trigger=timedelta(days=-1)), DisplayAlarm(trigger=timedelta(hours=-3))]
        cal.events.add(ev)
    return cal

def main():
    print("[eeclass-ICS] Logging in...")
    login()
    all_events = []
    for u in HOMEWORK_URLS:
        absu = to_abs(u)
        print(f"[eeclass-ICS] Fetch {absu}")
        r = sess.get(absu)
        r.raise_for_status()
        items = parse_list_page(r.text, absu)

        # Deep fetch if due not on list
        if DEEP_FETCH:
            enriched = []
            for title, dt0, url in items:
                if dt0 is None:
                    try:
                        rr = sess.get(url)
                        rr.raise_for_status()
                        dt1 = parse_detail_due(rr.text) or dt0
                    except Exception:
                        dt1 = dt0
                else:
                    dt1 = dt0
                enriched.append((title, dt1, url))
            items = enriched

        # Filter items without titles
        items = [(t, d, url) for (t, d, url) in items if t]
        print(f"  -> {sum(1 for _ in items)} candidates")
        all_events.extend(items)

    cal = build_calendar(all_events)
    out_path = ICS_OUTPUT
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(cal)
    print(f"[eeclass-ICS] Wrote {out_path}")
if __name__ == "__main__":
    main()
