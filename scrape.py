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

    # Cabinet role / responsibilities (Executive Roles)
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

    # Bio/statement
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
