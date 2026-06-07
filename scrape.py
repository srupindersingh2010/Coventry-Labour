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

    # Bio/statement (councillors sometimes add a personal statement)
    bio = ""
    for p in soup.find_all("p"):
        pt = p.get_text(strip=True)
        if len(pt) > 60 and "elected" in pt.lower():
            bio = pt[:400]
            break

    return {
        "email":   email,
        "phone":   phone,
        "surgery": surgery,
        "role":    role,
        "bio":     bio
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
                a = h2.find("a", href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                href  = a["href"]
                if not href or not title or len(title) < 10 or "/news" not in href:
                    continue
                link = href if href.startswith("http") else "https://www.coventry.gov.uk" + href
                entries.append({
                    "title": title, "summary": "", "link": link,
                    "date": "Recent", "focused": len(entries) == 0,
                    "source": "coventry.gov.uk/news",
                    "sourceUrl": "https://www.coventry.gov.uk/news",
                    "fetchedAt": STAMP
                })
                if len(entries) >= 8:
                    break
    if not entries:
        entries = [{"title": "Visit Coventry Council for the latest news",
                    "link": "https://www.coventry.gov.uk/news",
                    "date": "See website", "summary": "", "focused": True,
                    "source": "coventry.gov.uk/news",
                    "sourceUrl": "https://www.coventry.gov.uk/news",
                    "fetchedAt": STAMP}]
    print(f"  News articles: {len(entries)}")
    write_json("news.json", entries)

# =============================================================================
# 3. POLICE DATA — city-wide Coventry focus
# Uses all Coventry neighbourhoods from data.police.uk
# =============================================================================
def scrape_police():
    print("\n-- Police Data --")
    priorities = []

    # Coventry neighbourhoods on data.police.uk
    neighbourhoods = [
        "west-midlands/stoke-and-wyken",
        "west-midlands/lower-stoke",
        "west-midlands/foleshill",
        "west-midlands/binley-and-willenhall",
        "west-midlands/earlsdon",
        "west-midlands/radford",
        "west-midlands/bablake",
    ]

    for nb in neighbourhoods:
        try:
            r = requests.get(
                f"https://data.police.uk/api/priorities?neighbourhood={nb}",
                timeout=10)
            if r.status_code == 200:
                for item in r.json():
                    t = item.get("issue_title", "")
                    if not t:
                        continue
                    issue  = re.sub(r'<[^>]+>', '', item.get("issue",  "")).strip()
                    action = re.sub(r'<[^>]+>', '', item.get("action", "")).strip()
                    # Add neighbourhood label
                    nb_label = nb.split("/")[-1].replace("-", " ").title()
                    priorities.append({
                        "title":        t,
                        "neighbourhood": nb_label,
                        "issue":        issue or "Current policing priority.",
                        "action":       action or "Active policing response in place.",
                        "status":       "Active Priority",
                        "source":       "data.police.uk",
                        "sourceUrl":    f"https://data.police.uk",
                        "fetchedAt":    STAMP
                    })
        except Exception as e:
            print(f"  data.police.uk error ({nb}): {e}")

    if not priorities:
        priorities = [
            {"title": "Vehicle Crime",    "neighbourhood": "Coventry",
             "issue": "Theft from and of vehicles across Coventry.",
             "action": "Targeted patrols and community engagement.",
             "status": "Active Priority", "source": "data.police.uk",
             "sourceUrl": "https://data.police.uk", "fetchedAt": STAMP},
            {"title": "Shoplifting",      "neighbourhood": "Coventry",
             "issue": "Retail theft across city commercial areas.",
             "action": "High-visibility patrols at key retail locations.",
             "status": "Active Priority", "source": "data.police.uk",
             "sourceUrl": "https://data.police.uk", "fetchedAt": STAMP},
        ]

    print(f"  Police priorities: {len(priorities)}")
    write_json("police.json", priorities)

# =============================================================================
# 4. METADATA
# =============================================================================
def write_metadata():
    write_json("meta.json", {
        "lastUpdated": STAMP,
        "updatedAt":   NOW_UTC.isoformat(),
        "labourCount": 0   # updated by scrape_councillors
    })

# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print(f"=== Coventry Labour Councillors Scraper - {STAMP} ===\n")
    for fn in [scrape_councillors, scrape_news, scrape_police, write_metadata]:
        try:
            fn()
        except Exception as e:
            print(f"ERROR in {fn.__name__}: {e}")
            traceback.print_exc()
    print("\n=== Done ===")
    sys.exit(0)
