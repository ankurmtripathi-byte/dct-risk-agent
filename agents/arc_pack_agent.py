import json
from datetime import datetime

import anthropic
from flask import Blueprint, jsonify, render_template, request

from config import ANTHROPIC_API_KEY, MODEL_ANALYSIS
from database import get_db

arc_pack_bp = Blueprint("arc_pack", __name__)


def _risk_level(score: int) -> str:
    if score >= 13: return "High"
    if score >= 6:  return "Medium"
    return "Low"


# ── Routes ────────────────────────────────────────────────────────────────────

@arc_pack_bp.route("/arc-pack")
def arc_pack_page():
    return render_template("arc_pack.html")


@arc_pack_bp.route("/api/arc-packs", methods=["GET"])
def list_packs():
    conn = get_db()
    packs = [dict(r) for r in conn.execute(
        "SELECT id,title,period,generated_date,generated_by,status "
        "FROM arc_packs ORDER BY generated_date DESC"
    ).fetchall()]
    conn.close()
    return jsonify(packs)


@arc_pack_bp.route("/api/arc-packs/<int:pack_id>", methods=["GET"])
def get_pack(pack_id):
    conn = get_db()
    pack = conn.execute("SELECT * FROM arc_packs WHERE id=?", (pack_id,)).fetchone()
    conn.close()
    if not pack:
        return jsonify(error="Pack not found"), 404
    d = dict(pack)
    try:
        d["content_json"] = json.loads(d.get("content_json") or "{}")
    except (ValueError, TypeError):
        d["content_json"] = {}
    return jsonify(d)


@arc_pack_bp.route("/api/arc-pack/generate", methods=["POST"])
def generate_pack():
    if not ANTHROPIC_API_KEY:
        return jsonify(error="ANTHROPIC_API_KEY not configured"), 500

    data       = request.get_json(force=True) or {}
    period     = data.get("period", "Q1 2025")
    title      = data.get("title", f"DCT ARC Pack – {period}")
    generated_by = data.get("generated_by", "Risk Management Team")

    conn = get_db()

    # ── Gather risk data ──
    all_risks = [dict(r) for r in conn.execute(
        "SELECT * FROM risks ORDER BY risk_score DESC"
    ).fetchall()]
    total     = len(all_risks)
    high      = [r for r in all_risks if r["risk_score"] >= 13]
    medium    = [r for r in all_risks if 6 <= r["risk_score"] <= 12]
    low       = [r for r in all_risks if r["risk_score"] <= 5]

    by_level  = {}
    for r in all_risks:
        by_level.setdefault(r["level"], []).append(r)

    by_status = {}
    for r in all_risks:
        by_status.setdefault(r["status"], 0)
        by_status[r["status"]] += 1

    # ── Build top risks summary for prompt ──
    top10_text = "\n".join(
        f"- [{r['risk_id']}] {r['title']} | Level:{r['level']} | Score:{r['risk_score']} | Status:{r['status']}"
        for r in all_risks[:10]
    )

    prompt = f"""You are the DCT Chief Risk Officer preparing an Audit & Risk Committee (ARC) pack.
Period: {period}
Total risks in register: {total} ({len(high)} High / {len(medium)} Medium / {len(low)} Low)

Top 10 risks by score:
{top10_text}

Write a formal ARC Pack with these sections:
1. Executive Summary (3-4 sentences on overall risk posture)
2. Key Risk Highlights (bullet points for top 5 risks requiring committee attention)
3. Risk Trend Analysis (2-3 sentences on how the risk landscape has evolved)
4. Management Actions & Progress (2-3 sentences on mitigation progress)
5. Forward-Looking Concerns (2-3 sentences on emerging risks)
6. Recommendations to Committee (3-5 numbered recommendations)

Write in formal government report style suitable for senior officials."""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=MODEL_ANALYSIS,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        narrative = msg.content[0].text.strip()
    except TypeError as e:
        conn.close()
        return jsonify(error=f"API key error: {e}"), 500
    except anthropic.AuthenticationError:
        conn.close()
        return jsonify(error="Invalid Anthropic API key"), 401
    except Exception as e:  # noqa: BLE001
        conn.close()
        return jsonify(error=f"AI generation failed: {e}"), 500

    # ── Assemble content JSON ──
    content = {
        "period":    period,
        "title":     title,
        "summary": {
            "total": total, "high": len(high),
            "medium": len(medium), "low": len(low),
        },
        "by_level":   {k: len(v) for k, v in by_level.items()},
        "by_status":  by_status,
        "top_risks":  [{"risk_id": r["risk_id"], "title": r["title"],
                        "level": r["level"], "score": r["risk_score"],
                        "level_label": _risk_level(r["risk_score"]),
                        "status": r["status"], "owner": r["owner"]}
                       for r in all_risks[:10]],
        "narrative":  narrative,
    }

    # ── Build HTML output ──
    html = _render_html(content, generated_by)

    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO arc_packs (title,period,generated_date,generated_by,status,content_json,html_output)
        VALUES (?,?,?,?,?,?,?)
    """, (title, period, now, generated_by, "Draft", json.dumps(content), html))
    conn.commit()
    pack_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    return jsonify(id=pack_id, title=title, content=content), 201


def _render_html(content: dict, generated_by: str) -> str:
    top = "".join(
        f"<tr><td>{r['risk_id']}</td><td>{r['title']}</td>"
        f"<td>{r['level'].capitalize()}</td>"
        f"<td class='score-{r['level_label'].lower()}'>{r['score']}</td>"
        f"<td>{r['level_label']}</td><td>{r['status']}</td><td>{r['owner']}</td></tr>"
        for r in content.get("top_risks", [])
    )
    narrative_html = content.get("narrative","").replace("\n","<br>")
    s = content.get("summary", {})
    return f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;color:#1a2744;margin:0;padding:32px;}}
  h1{{color:#0a1628;border-bottom:3px solid #1e6fb5;padding-bottom:8px;}}
  h2{{color:#1e6fb5;margin-top:28px;}}
  .stat-row{{display:flex;gap:20px;margin:20px 0;}}
  .stat{{background:#f0f4ff;border-radius:8px;padding:16px 24px;text-align:center;}}
  .stat .n{{font-size:2em;font-weight:700;color:#1e6fb5;}}
  .stat.high .n{{color:#ef4444;}}
  .stat.medium .n{{color:#f59e0b;}}
  .stat.low .n{{color:#22c55e;}}
  table{{width:100%;border-collapse:collapse;margin-top:12px;}}
  th{{background:#0a1628;color:#fff;padding:10px 12px;text-align:left;}}
  td{{padding:9px 12px;border-bottom:1px solid #e4e9f0;}}
  tr:hover{{background:#f8faff;}}
  .score-high{{color:#ef4444;font-weight:700;}}
  .score-medium{{color:#f59e0b;font-weight:700;}}
  .score-low{{color:#22c55e;font-weight:700;}}
  .narrative{{background:#f8faff;border-left:4px solid #1e6fb5;padding:20px;border-radius:4px;line-height:1.7;}}
  .footer{{margin-top:40px;font-size:11px;color:#6b7280;border-top:1px solid #e4e9f0;padding-top:12px;}}
</style></head>
<body>
<h1>&#128196; {content.get('title','DCT ARC Pack')}</h1>
<p style="color:#6b7280">Period: {content.get('period','')} &nbsp;|&nbsp; Generated by: {generated_by}</p>
<div class="stat-row">
  <div class="stat"><div class="n">{s.get('total',0)}</div><div>Total Risks</div></div>
  <div class="stat high"><div class="n">{s.get('high',0)}</div><div>High</div></div>
  <div class="stat medium"><div class="n">{s.get('medium',0)}</div><div>Medium</div></div>
  <div class="stat low"><div class="n">{s.get('low',0)}</div><div>Low</div></div>
</div>
<h2>AI-Generated Narrative</h2>
<div class="narrative">{narrative_html}</div>
<h2>Top 10 Risks by Score</h2>
<table>
  <thead><tr><th>Risk ID</th><th>Title</th><th>Level</th><th>Score</th><th>Rating</th><th>Status</th><th>Owner</th></tr></thead>
  <tbody>{top}</tbody>
</table>
<div class="footer">DCT Risk Intelligence Platform &nbsp;&middot;&nbsp; Department of Culture and Tourism &nbsp;&middot;&nbsp; For official use only</div>
</body></html>"""
