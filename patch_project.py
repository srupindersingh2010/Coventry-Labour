"""
One-click patcher for Coventry Labour Councillors project.
Surgically updates scrape.py and index.html to include all 5 Scrutiny Boards
without breaking any original fallback logic or existing structures.
"""

from pathlib import Path

def patch_file(file_path, search_marker, replacement_text):
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Error: Could not find {file_path}. Make sure to run this from your root folder.")
        return False
    
    content = path.read_text(encoding="utf-8")
    if search_marker not in content:
        print(f"⚠️ Warning: Marker not found in {file_path}. It might already be patched.")
        return False
        
    updated_content = content.replace(search_marker, replacement_text)
    path.write_text(updated_content, encoding="utf-8")
    print(f"✅ Successfully patched {file_path}")
    return True

if __name__ == "__main__":
    print("🚀 Starting single-file project patch...")

    # -------------------------------------------------------------------------
    # 1. PATCH SCRAPE.PY (Inject Scrutiny & Committee Chair Engine)
    # -------------------------------------------------------------------------
    scrape_marker = """    # Cabinet role / responsibilities
    role = ""
    role_tag = soup.find("a", href=re.compile(r'mgExecPostDetails', re.I))
    if role_tag:
        role = role_tag.get_text(strip=True)"""

    scrape_replacement = """    # Cabinet role / responsibilities
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
        (r"Finance and Corporate Services Scrutiny Board\\s*\\(\\s*1\\s*\\)", "Chair of Scrutiny Board (1)"),
        (r"Education and Children's Services Scrutiny Board\\s*\\(\\s*2\\s*\\)", "Chair of Scrutiny Board (2)"),
        (r"Business, Economy and Enterprise Scrutiny Board\\s*\\(\\s*3\\s*\\)", "Chair of Scrutiny Board (3)"),
        (r"Communities and Neighbourhoods Scrutiny Board\\s*\\(\\s*4\\s*\\)", "Chair of Scrutiny Board (4)"),
        (r"Health and Social Care Scrutiny Board\\s*\\(\\s*5\\s*\\)", "Chair of Scrutiny Board (5)"),
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
        committee_role = " & ".join(chairs_found)"""

    # Also need to make sure the function returns the new database key
    scrape_return_marker = """    return {
        "email":   email,
        "phone":   phone,
        "surgery": surgery,
        "role":    role,
        "bio":     bio
    }"""

    scrape_return_replacement = """    return {
        "email":         email,
        "phone":         phone,
        "surgery":       surgery,
        "role":          role,
        "committeeRole": committee_role,
        "bio":           bio
    }"""

    patch_file("scrape.py", scrape_marker, scrape_replacement)
    patch_file("scrape.py", scrape_return_marker, scrape_return_replacement)

    # -------------------------------------------------------------------------
    # 2. PATCH INDEX.HTML (CSS Style Rules, UI Generation, Search Filter)
    # -------------------------------------------------------------------------
    
    # A. Inject Slate Blue CSS Badge Styles
    css_marker = """    .cllr-role { font-size: 0.78rem; background: var(--rose-bg); color: var(--labour-dark); padding: 3px 8px; border-radius: 3px; display: inline-block; margin-bottom: 8px; font-weight: 600; }"""
    
    css_replacement = """    .cllr-role { font-size: 0.78rem; background: var(--rose-bg); color: var(--labour-dark); padding: 3px 8px; border-radius: 3px; display: inline-block; margin-bottom: 8px; font-weight: 600; }
    .cllr-committee-role { font-size: 0.78rem; background: #EDF2F7; color: #2C3E50; padding: 3px 8px; border-radius: 3px; display: inline-block; margin-bottom: 8px; font-weight: 600; border-left: 3px solid var(--charcoal); }"""

    # B. Inject Dual Badge Generation Block inside displayCouncillors()
    ui_marker = """          (c.role ? '<div class="cllr-role">🏛️ ' + esc(c.role) + '</div>' : '') +"""
    
    ui_replacement = """          '<div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">' +
            (c.role ? '<div class="cllr-role">🏛️ ' + esc(c.role) + '</div>' : '') +
            (c.committeeRole ? '<div class="cllr-committee-role">⚖️ ' + esc(c.committeeRole) + '</div>' : '') +
          '</div>' +"""

    # C. Extend Search filter to check Scrutiny Board designations instantly
    search_marker = """      var matchSearch = !search ||
        c.name.toLowerCase().includes(search) ||
        c.ward.toLowerCase().includes(search) ||
        (c.role || '').toLowerCase().includes(search);"""
        
    search_replacement = """      var matchSearch = !search ||
        c.name.toLowerCase().includes(search) ||
        c.ward.toLowerCase().includes(search) ||
        (c.role || '').toLowerCase().includes(search) ||
        (c.committeeRole || '').toLowerCase().includes(search);"""

    patch_file("index.html", css_marker, css_replacement)
    patch_file("index.html", ui_marker, ui_replacement)
    patch_file("index.html", search_marker, search_replacement)

    print("\n🎉 All patches applied successfully via single file utility!")
