"""
Coventry Labour Councillors — Daily Data Scraper
Runs via GitHub Actions every day at 08:00.
Scrapes all Labour councillors from edemocracy.coventry.gov.uk
plus council news, police data and community info.
"""

import json, re, sys, traceback, csv, io, time
from datetime import datetime, timezone, timedelta, date as dt_date
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

NOW_UTC = datetime.now(timezone.utc)
NOW_UK  = NOW_UTC + timedelta(hours=1)
STAMP   = NOW_UK.strftime("%-d %B %Y at %H:%M")

EDEM_BASE = "https://edemocracy.coventry.gov.uk"
WMP_BASE  = "https://www.westmidlands.police.uk/area/your-area/west-midlands/coventry"
WMP_SUFFIX = "top-reported-crimes-in-this-area"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

def safe_get(url, timeout=20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        print(f"  GET {url[:80]} -> {r.status_code} ({len(r.text)} chars)")
        return r
    except Exception as e:
        print(f"  GET {url[:80]} -> ERROR: {e}")
        return None

def write_json(filename, data):
    path = DATA_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote {filename} ({len(data) if isinstance(data, list) else 'object'})")

def fmt_date(iso_date):
    try:
        d = dt_date.fromisoformat(str(iso_date)[:10])
        return d.strftime("%-d %b %Y")
    except Exception:
        return str(iso_date)

# =============================================================================
# 1. LABOUR COUNCILLORS
# Scrapes the full councillor list, filters for Labour only,
# then fetches each profile page for contact details.
# =============================================================================
def scrape_councillors():
    print("\n-- Labour Councillors --")
    councillors = []

    # Step 1: Get the full councillor list (all parties, all wards)
    list_url = f"{EDEM_BASE}/mgMemberIndex.aspx?FN=WARD&VW=LIST&PIC=1"
    r = safe_get(list_url)
    if not r or r.status_code != 200:
        print("  Could not fetch councillor list")
        write_json("councillors.json", [])
        return

    soup = BeautifulSoup(r.text, "html.parser")

    # Parse each ward section
    current_ward = ""
    entries = []  # list of {uid, name, ward, party, photo}

    for tag in soup.find_all(["h2", "li"]):
        if tag.name == "h2":
            current_ward = tag.get_text(strip=True)
        elif tag.name == "li":
            a = tag.find("a", href=re.compile(r'mgUserInfo', re.I))
            if not a:
                continue
            name = a.get_text(strip=True)
            href = a.get("href", "")
            uid_m = re.search(r'UID=(\d+)', href, re.I)
            if not uid_m:
                continue
            uid = uid_m.group(1)

            # Party text is in the li but outside the link
            li_text = tag.get_text(" ", strip=True)
            party = ""
            for p in ["Labour", "Conservative", "Green", "Reform", "Liberal"]:
                if p.lower() in li_text.lower():
                    party = p
                    break

            # Photo URL from img tag
            img = tag.find("img")
            photo = ""
            if img and img.get("src"):
                src = img["src"]
                photo = src if src.startswith("http") else EDEM_BASE + src
                # Use bigpic instead of smallpic for better quality
                photo = photo.replace("smallpic", "bigpic")

            entries.append({
                "uid":   uid,
                "name":  name.replace("Councillor ", "").strip(),
                "ward":  current_ward,
                "party": party,
                "photo": photo,
                "profileUrl": f"{EDEM_BASE}/mgUserInfo.aspx?UID={uid}"
            })

    # Filter Labour only
    labour_entries = [e for e in entries if e["party"] == "Labour"]
    print(f"  Total councillors found: {len(entries)}, Labour: {len(labour_entries)}")

    # Step 2: Fetch each Labour councillor's profile for contact details
    for i, cllr in enumerate(labour_entries):
        print(f"  Profile {i+1}/{len(labour_entries)}: {cllr['name']}")
        profile = scrape_councillor_profile(cllr["uid"])
        cllr.update(profile)
        cllr["fetchedAt"] = STAMP
        councillors.append(cllr)
        # Be polite — small delay between requests
        time.sleep(0.5)

    print(f"  Total Labour councillors scraped: {len(councillors)}")
    # Sort by ward then name
    councillors.sort(key=lambda x: (x.get("ward",""), x.get("name","")))
    write_json("councillors.json", councillors)

def scrape_councillor_profile(uid):
    """Fetch contact details from an individual councillor's profile page."""
    r = safe_get(f"{EDEM_BASE}/mgUserInfo.aspx?UID={uid}")
    if not r or r.status_code != 200:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Email
    email = ""
    email_tag = soup.find("a", href=re.compile(r'mailto:', re.I))
    if email_tag:
        email = email_tag["href"].replace("mailto:", "").strip()
    if not email:
        em = re.search(r'[\w.\-]+@coventry\.gov\.uk', text)
        if em:
            email = em.group()

    # Phone
    phone = ""
    phone_m = re.search(r'(?:Bus\.?\s*phone|Phone|Tel)[:\s]*([\d\s]{10,15})', text, re.I)
    if phone_m:
        phone = phone_m.group(1).strip()

    # Surgery details
    surgery = ""
    surgery_m = re.search(r'Surgery[^:]*:(.*?)(?:Contact|$)', text, re.I | re.S)
    if surgery_m:
        surgery = " ".join(surgery_m.group(1).split())[:300]

    # Cabinet role / responsibilities
    role = ""
    role_tag = soup.find("a", href=re.compile(r'mgExecPostDetails', re.I))
    if role_tag:
        role = role_tag.get_text(strip=True)

    # --- Committee & Scrutiny Board Chair Extraction Engine ---
    committee_role = ""
    chairs_found = []

    # Map text patterns found in profile timelines/tables to clean titles
    patterns = [
        (r"Scrutiny Co-ordination Committee", "Chair of Scrutiny Co-ordination"),
        (r"Finance and Corporate Services Scrutiny Board\s*\(\s*1\s*\)", "Chair of Scrutiny Board (1)"),
        (r"Education and Children's Services Scrutiny Board\s*\(\s*2\s*\)", "Chair of Scrutiny Board (2)"),
        (r"Business, Economy and Enterprise Scrutiny Board\s*\(\s*3\s*\)", "Chair of Scrutiny Board (3)"),
        (r"Communities and Neighbourhoods Scrutiny Board\s*\(\s*4\s*\)", "Chair of Scrutiny Board (4)"),
        (r"Health and Social Care Scrutiny Board\s*\(\s*5\s*\)", "Chair of Scrutiny Board (5)"),
        (r"Planning Committee", "Chair of Planning Committee"),
        (r"Licensing and Regulatory Committee", "Chair of Licensing Committee"),
        (r"Audit and Procurement Committee", "Chair of Audit Committee")
    ]

    # Traverse layout nodes looking for references to "Chair" or "Chairman"
    for element in soup.find_all(["li", "p", "td", "div"]):
        el_text = " ".join(element.get_text(" ", strip=True).split())
        if "chair" in el_text.lower() or "chairman" in el_text.lower():
            for regex, display_name in patterns:
                if re.search(regex, el_text, re.I):
                    if display_name not in chairs_found:
                        chairs_found.append(display_name)

    if chairs_found:
        committee_role = " & ".join(chairs_found)

    # Bio/statement (councillors sometimes add a personal statement)
    bio = ""
    for p in soup.find_all("p"):
        pt = p.get_text(strip=True)
        if len(pt) > 60 and "elected" in pt.lower():
            bio = pt[:400]
            break

    return {
        "email":         email,
        "phone":         phone,
        "surgery":       surgery,
        "role":          role,
        "committeeRole": committee_role,
        "bio":           bio
    }

# =============================================================================
# 2. COVENTRY COUNCIL NEWS
# =============================================================================
def scrape_news():
    print("\n-- Council News --")
    entries = []
    r = safe_get("https://www.coventry.gov.uk/news")
    if r and r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for li in soup.find_all("li"):
            h2 = li.find("h2")
            if not h2:
                continue
            a = h2.find("a", href=True)
            if not a:
                continue
            title = a.get_text(strip=True)
            href  = a["href"]
            if not href or not title or title in seen or len(title) < 10:
                continue
            if "/news" not in href:
                continue
            seen.add(title)
            link = href if href.startswith("http") else "https://www.coventry.gov.uk" + href
            date_str = ""
            strong = li.find("strong", string=re.compile(r"Published", re.I))
            if strong:
                date_str = strong.get_text(strip=True).replace("Published:", "").strip()
            summary = ""
            p = li.find("p")
            if p:
                summary = p.get_text(strip=True)[:200]
            entries.append({
                "title": title, "summary": summary, "link": link,
                "date": date_str or "Recent", "focused": len(entries) == 0,
                "source": "coventry.gov.uk/news",
                "sourceUrl": "https://www.coventry.gov.uk/news",
                "fetchedAt": STAMP
            })
            if len(entries) >= 8:
                break
        # Fallback h2 scan
        if not entries:
            for h2 in soup.find_all("h2"):
                a = h2.find("a", href=True
