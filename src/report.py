"""
Generate a self-contained HTML job report from the jobs database.
"""

import sqlite3
import textwrap
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
}


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


def generate_report(output_path=None) -> Path:
    """Build the HTML report and return the path it was written to."""
    output_path = output_path or DATA_DIR / "jobs_report.html"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company, location, url, description, source,
               match_score, status, cover_letter, notes, created_at
        FROM jobs
        WHERE status NOT IN ('found')
        ORDER BY match_score DESC, created_at DESC
    """)
    rows = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM jobs")
    total = cur.fetchone()[0]

    cur.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
    by_status = dict(cur.fetchall())

    conn.close()

    now = datetime.now().strftime("%d %b %Y, %H:%M")

    # ── Build rows HTML ────────────────────────────────────────────────────
    rows_html = ""
    for i, r in enumerate(rows):
        src_icon = SOURCE_EMOJI.get(r["source"], "🌐")
        cover_id = f"cl_{r['id']}"
        cover_html = ""
        if r["cover_letter"]:
            escaped = r["cover_letter"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
        rows_html += f"""
        <tr style="border-bottom:1px solid #f3f4f6" onmouseover="this.style.background='#fafafa'" onmouseout="this.style.background=''"  >
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

    # ── Stat cards ─────────────────────────────────────────────────────────
    cards = ""
    card_defs = [
        ("Total found",    str(total),                           "#4f46e5"),
        ("To apply",       str(by_status.get("manual_required", 0)), "#f59e0b"),
        ("Applied",        str(by_status.get("applied", 0)),    "#10b981"),
        ("Emailed",        str(by_status.get("emailed", 0)),    "#8b5cf6"),
    ]
    for label, val, color in card_defs:
        cards += f"""
        <div style="background:#fff;border-radius:10px;padding:16px 24px;
                    box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center;min-width:110px">
          <div style="font-size:1.8rem;font-weight:700;color:{color}">{val}</div>
          <div style="font-size:0.78rem;color:#6b7280;margin-top:2px">{label}</div>
        </div>"""

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
  </style>
</head>
<body>
<div style="max-width:1200px;margin:0 auto;padding:32px 20px">

  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px">
    <div>
      <h1>AutomateResume — Job Report</h1>
      <p style="font-size:0.82rem;color:#9ca3af;margin-top:4px">Generated {now} &nbsp;·&nbsp; showing matched &amp; manual-apply jobs</p>
    </div>
  </div>

  <!-- Stat cards -->
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px">
    {cards}
  </div>

  <!-- Filters -->
  <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
    <input type="text" id="search" placeholder="🔍  Search title, company, location…" style="max-width:360px"
           oninput="filterTable()">
    <select id="statusFilter" onchange="filterTable()">
      <option value="">All statuses</option>
      <option value="manual_required">To Apply</option>
      <option value="applied">Applied</option>
      <option value="matched">Matched</option>
      <option value="emailed">Emailed</option>
    </select>
    <select id="sourceFilter" onchange="filterTable()">
      <option value="">All sources</option>
      <option value="linkedin">LinkedIn</option>
      <option value="seek">Seek</option>
      <option value="stepstone">StepStone</option>
    </select>
  </div>

  <!-- Table -->
  <table id="jobTable">
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
    <tbody id="tableBody">
      {rows_html}
    </tbody>
  </table>
  <p id="rowCount" style="margin-top:10px;font-size:0.8rem;color:#9ca3af"></p>

</div>

<script>
function filterTable() {{
  const q      = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value.toLowerCase();
  const source = document.getElementById('sourceFilter').value.toLowerCase();
  const rows   = document.querySelectorAll('#tableBody tr');
  let visible  = 0;
  rows.forEach(row => {{
    const text = row.innerText.toLowerCase();
    const show = (!q || text.includes(q))
              && (!status || text.includes(status.replace('_',' ')))
              && (!source || text.includes(source));
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('rowCount').textContent = visible + ' job' + (visible !== 1 ? 's' : '') + ' shown';
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

// init count
filterTable();
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
