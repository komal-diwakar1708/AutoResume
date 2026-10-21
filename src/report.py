"""
Generate a self-contained HTML job report from the jobs database.

Jobs are grouped into SEPARATE lists per country, with a navigation bar and
a global search/filter that works across all country sections.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "jobs.db"

STATUS_COLOR = {
    "applied":         ("#d1fae5", "#065f46"),   # green
    "manual_required": ("#fef3c7", "#92400e"),   # amber
    "matched":         ("#dbeafe", "#1e40af"),   # blue
    "found":           ("#f3f4f6", "#374151"),   # grey
    "emailed":         ("#ede9fe", "#5b21b6"),   # purple
}

SOURCE_EMOJI = {
    "linkedin": "🔗",
    "seek":     "🔍",
    "stepstone":"💼",
    "jsearch":  "🌐",
    "mycareersfuture": "🇸🇬",
    "efinancialcareers": "💰",
    "wantedly": "🎌",
}

# ── Country detection ────────────────────────────────────────────────────────
# Order here is the display order of the per-country sections.
# Each entry: canonical name → (flag, [keywords to match in the location string])
COUNTRY_RULES = [
    ("India",          "🇮🇳", ["india", "bengaluru", "bangalore", "pune", "mumbai",
                                "hyderabad", "gurgaon", "gurugram", "delhi", "noida",
                                "karnataka", "maharashtra", "telangana", "chennai",
                                "kolkata", "ahmedabad", "haryana"]),
    ("Germany",        "🇩🇪", ["germany", "deutschland", "berlin", "munich", "münchen",
                                "hamburg", "frankfurt", "stuttgart", "cologne", "köln",
                                "düsseldorf", "dusseldorf", "bavaria", "hesse", "saxony",
                                "rhine", "westphalia", "baden-württemberg", "nuremberg"]),
    ("Singapore",      "🇸🇬", ["singapore"]),
    ("Japan",          "🇯🇵", ["japan", "tokyo", "osaka", "kyoto", "yokohama"]),
    ("Australia",      "🇦🇺", ["australia", "sydney", "melbourne", "brisbane", "perth",
                                "adelaide", "canberra", "new south wales", "victoria",
                                "queensland"]),
    ("New Zealand",    "🇳🇿", ["new zealand", "auckland", "wellington", "christchurch"]),
    ("Canada",         "🇨🇦", ["canada", "toronto", "montreal", "vancouver", "ottawa",
                                "calgary", "ontario", "quebec", "british columbia", "alberta"]),
    ("United Kingdom", "🇬🇧", ["united kingdom", "london", "manchester", "england",
                                "scotland", "wales", "birmingham", "edinburgh", "bristol",
                                "leeds", "glasgow"]),
    ("Netherlands",    "🇳🇱", ["netherlands", "amsterdam", "rotterdam", "the hague",
                                "utrecht", "eindhoven", "holland"]),
    ("United Arab Emirates", "🇦🇪", ["united arab emirates", "uae", "dubai", "abu dhabi",
                                      "sharjah"]),
]

OTHER = ("Other / Unspecified", "🌐")


def _country_of(location: str) -> tuple[str, str]:
    """Map a location string to (country_name, flag). Falls back to Other."""
    if not location or not location.strip():
        return OTHER
    loc = location.lower()
    for name, flag, keywords in COUNTRY_RULES:
        if any(kw in loc for kw in keywords):
            return (name, flag)
    return OTHER


def _badge(status: str) -> str:
    bg, fg = STATUS_COLOR.get(status, ("#f3f4f6", "#374151"))
    label = status.replace("_", " ").title()
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:12px;'
        f'font-size:0.75rem;font-weight:600;white-space:nowrap">{label}</span>'
    )


def _score_bar(score: float) -> str:
    pct = int(score * 100)
    color = "#10b981" if pct >= 70 else "#f59e0b" if pct >= 50 else "#6b7280"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="width:60px;background:#e5e7eb;border-radius:4px;height:8px">'
        f'<div style="width:{pct}%;background:{color};height:8px;border-radius:4px"></div>'
        f'</div>'
        f'<span style="font-size:0.8rem;color:#374151">{pct}%</span>'
        f'</div>'
    )


def _snippet(text: str, max_chars: int = 200) -> str:
    if not text:
        return "<em style='color:#9ca3af'>—</em>"
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rsplit(" ", 1)[0] + "…"


def _row_html(r) -> str:
    """Build one <tr> for a job row."""
    src_icon = SOURCE_EMOJI.get(r["source"], "🌐")
    cover_id = f"cl_{r['id']}"
    cover_html = ""
    if r["cover_letter"]:
        escaped = (r["cover_letter"].replace("&", "&amp;")
                   .replace("<", "&lt;").replace(">", "&gt;"))
        cover_html = (
            f'<details style="margin-top:8px">'
            f'<summary style="cursor:pointer;font-size:0.78rem;color:#6366f1;user-select:none">'
            f'📄 Cover letter</summary>'
            f'<pre id="{cover_id}" style="white-space:pre-wrap;font-size:0.75rem;'
            f'background:#f8f9fa;padding:10px;border-radius:6px;margin-top:6px;'
            f'max-height:200px;overflow-y:auto;border:1px solid #e5e7eb">'
            f'{escaped}</pre>'
            f'<button onclick="copyText(\'{cover_id}\')" '
            f'style="margin-top:4px;font-size:0.72rem;padding:2px 8px;cursor:pointer;'
            f'border:1px solid #d1d5db;border-radius:4px;background:#fff">'
            f'Copy</button>'
            f'</details>'
        )
    return f"""
        <tr style="border-bottom:1px solid #f3f4f6" onmouseover="this.style.background='#fafafa'" onmouseout="this.style.background=''">
          <td style="padding:12px 10px;font-size:0.85rem">
            <strong>{r['title'] or '—'}</strong><br>
            <span style="color:#6b7280;font-size:0.78rem">{r['company'] or '—'}</span>
          </td>
          <td style="padding:12px 10px;font-size:0.82rem;color:#374151;white-space:nowrap">{r['location'] or '—'}</td>
          <td style="padding:12px 10px">{_score_bar(r['match_score'] or 0)}</td>
          <td style="padding:12px 10px">{_badge(r['status'])}</td>
          <td style="padding:12px 10px;font-size:0.78rem;color:#6b7280;max-width:280px">
            {_snippet(r['description'])}
            {cover_html}
          </td>
          <td style="padding:12px 10px;font-size:0.8rem">{src_icon} {r['source']}</td>
          <td style="padding:12px 10px;white-space:nowrap">
            <a href="{r['url']}" target="_blank"
               style="display:inline-block;padding:5px 12px;background:#4f46e5;color:#fff;
                      border-radius:6px;text-decoration:none;font-size:0.8rem;font-weight:600">
              Apply ↗
            </a>
          </td>
        </tr>"""


def generate_report(output_path=None) -> Path:
    """Build the HTML report (grouped by country) and return its path."""
    output_path = output_path or DATA_DIR / "jobs_report.html"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company, location, url, description, source,
               match_score, status, cover_letter, notes, created_at
        FROM jobs
        ORDER BY match_score DESC, created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()

    # ── Group rows by country ───────────────────────────────────────────────
    groups: dict[str, dict] = {}
    for r in rows:
        name, flag = _country_of(r["location"] or "")
        g = groups.setdefault(name, {"flag": flag, "rows": []})
        g["rows"].append(r)

    # Order: configured countries first (in COUNTRY_RULES order), Other last
    ordered_names = [c[0] for c in COUNTRY_RULES if c[0] in groups]
    if OTHER[0] in groups:
        ordered_names.append(OTHER[0])

    total = len(rows)
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    # ── Country navigation chips ─────────────────────────────────────────────
    nav_chips = ""
    for name in ordered_names:
        g = groups[name]
        anchor = name.lower().replace(" ", "-").replace("/", "")
        nav_chips += (
            f'<a href="#c-{anchor}" '
            f'style="display:inline-flex;align-items:center;gap:6px;padding:6px 12px;'
            f'background:#fff;border:1px solid #e5e7eb;border-radius:20px;'
            f'text-decoration:none;color:#374151;font-size:0.82rem;font-weight:600">'
            f'{g["flag"]} {name} '
            f'<span style="color:#9ca3af;font-weight:400">{len(g["rows"])}</span></a>'
        )

    # ── Per-country sections ─────────────────────────────────────────────────
    sections = ""
    for name in ordered_names:
        g = groups[name]
        anchor = name.lower().replace(" ", "-").replace("/", "")
        body_rows = "".join(_row_html(r) for r in g["rows"])
        sections += f"""
  <section class="country-block" data-country="{name.lower()}" id="c-{anchor}" style="margin-bottom:40px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <h2 style="font-size:1.2rem;font-weight:700">{g['flag']} {name}
        <span style="color:#9ca3af;font-weight:400;font-size:0.95rem">· {len(g['rows'])} openings</span>
      </h2>
      <a href="#top" style="font-size:0.78rem;color:#6366f1;text-decoration:none">↑ back to top</a>
    </div>
    <table>
      <thead>
        <tr>
          <th>Job Title / Company</th>
          <th>Location</th>
          <th>Match</th>
          <th>Status</th>
          <th>Requirements</th>
          <th>Source</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {body_rows}
      </tbody>
    </table>
    <p class="empty-msg" style="display:none;color:#9ca3af;font-size:0.82rem;padding:12px 0">No matching jobs in this country.</p>
  </section>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AutomateResume — Job Report</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f9fafb; color: #111827; }}
    h1 {{ font-size: 1.5rem; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 10px; overflow: hidden;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    th {{ text-align: left; padding: 10px 10px; font-size: 0.75rem;
          text-transform: uppercase; letter-spacing: .05em;
          color: #6b7280; background: #f9fafb;
          border-bottom: 1px solid #e5e7eb; }}
    input[type=text] {{ width: 100%; padding: 8px 12px; border: 1px solid #d1d5db;
                        border-radius: 8px; font-size: 0.9rem; outline: none; }}
    input[type=text]:focus {{ border-color: #6366f1; }}
    select {{ padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px;
              font-size: 0.85rem; outline: none; background: #fff; }}
    .toolbar {{ position: sticky; top: 0; background: #f9fafb; padding: 12px 0;
                z-index: 10; }}
  </style>
</head>
<body>
<div id="top" style="max-width:1200px;margin:0 auto;padding:32px 20px">

  <div style="margin-bottom:20px">
    <h1>AutomateResume — Job Report</h1>
    <p style="font-size:0.82rem;color:#9ca3af;margin-top:4px">
      Generated {now} &nbsp;·&nbsp; {total} openings across {len(ordered_names)} countries
      &nbsp;·&nbsp; Product Manager / Associate Product Manager
    </p>
  </div>

  <!-- Country navigation -->
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px">
    {nav_chips}
  </div>

  <!-- Filters (sticky) -->
  <div class="toolbar">
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <input type="text" id="search" placeholder="🔍  Search title, company, location…" style="max-width:360px"
             oninput="filterAll()">
      <select id="statusFilter" onchange="filterAll()">
        <option value="">All statuses</option>
        <option value="found">New / Found</option>
        <option value="manual_required">To Apply</option>
        <option value="applied">Applied</option>
        <option value="matched">Matched</option>
        <option value="emailed">Emailed</option>
      </select>
      <select id="sourceFilter" onchange="filterAll()">
        <option value="">All sources</option>
        <option value="linkedin">LinkedIn</option>
        <option value="seek">Seek</option>
        <option value="stepstone">StepStone</option>
      </select>
      <span id="rowCount" style="align-self:center;font-size:0.8rem;color:#9ca3af"></span>
    </div>
  </div>

  <!-- Per-country sections -->
  {sections}

</div>

<script>
function filterAll() {{
  const q      = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value.toLowerCase();
  const source = document.getElementById('sourceFilter').value.toLowerCase();
  let totalVisible = 0;

  document.querySelectorAll('.country-block').forEach(block => {{
    const rows = block.querySelectorAll('tbody tr');
    let shown = 0;
    rows.forEach(row => {{
      const text = row.innerText.toLowerCase();
      const ok = (!q || text.includes(q))
              && (!status || text.includes(status.replace('_',' ')))
              && (!source || text.includes(source));
      row.style.display = ok ? '' : 'none';
      if (ok) shown++;
    }});
    // Hide the whole country section if nothing matches
    block.style.display = shown ? '' : 'none';
    totalVisible += shown;
  }});

  document.getElementById('rowCount').textContent =
    totalVisible + ' job' + (totalVisible !== 1 ? 's' : '') + ' shown';
}}

function copyText(id) {{
  const el = document.getElementById(id);
  if (navigator.clipboard) {{
    navigator.clipboard.writeText(el.innerText);
  }} else {{
    const r = document.createRange();
    r.selectNode(el);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(r);
    document.execCommand('copy');
  }}
}}

filterAll();
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
