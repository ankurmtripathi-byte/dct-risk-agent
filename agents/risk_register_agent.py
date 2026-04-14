import json
import sqlite3
from datetime import datetime

import anthropic
from flask import Blueprint, jsonify, render_template, request

from config import ANTHROPIC_API_KEY, DB_PATH, MODEL_ANALYSIS
from database import get_db

risk_register_bp = Blueprint("risk_register", __name__)

LEVEL_PREFIX = {
    "enterprise": "ENT",
    "affiliate":  "AFF",
    "department": "DEP",
    "event":      "EVT",
}

# ── JSON Schema for structured output ────────────────────────────────────────

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category":        {"type": "string"},
                    "title":           {"type": "string"},
                    "description":     {"type": "string"},
                    "ai_correlation":  {"type": "string"},
                    "likelihood":      {"type": "integer"},
                    "impact":          {"type": "integer"},
                    "velocity":        {"type": "string"},
                    "mitigation":      {"type": "string"},
                    "contingency":     {"type": "string"},
                    "owner":           {"type": "string"},
                    "reviewer":        {"type": "string"},
                    "kri":             {"type": "string"},
                    "kri_threshold":   {"type": "string"},
                },
                "required": [
                    "category", "title", "description", "ai_correlation",
                    "likelihood", "impact", "velocity",
                    "mitigation", "contingency", "owner", "reviewer",
                    "kri", "kri_threshold",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["risks"],
    "additionalProperties": False,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_risk_id(level: str, conn) -> str:
    prefix = LEVEL_PREFIX.get(level, "RSK")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM risks WHERE level = ?", (level,)
    ).fetchone()
    return f"{prefix}-{(row['c'] or 0) + 1:03d}"


def _risk_row(row) -> dict:
    d = dict(row)
    try:
        d["event_context"] = json.loads(d.get("event_context") or "{}")
    except (ValueError, TypeError):
        d["event_context"] = {}
    return d


# ── Routes ────────────────────────────────────────────────────────────────────

@risk_register_bp.route("/risk-register")
def risk_register_page():
    return render_template("risk_register.html")


@risk_register_bp.route("/api/risks/stats")
def risk_stats():
    conn = get_db()
    total  = conn.execute("SELECT COUNT(*) AS c FROM risks").fetchone()["c"]
    high   = conn.execute("SELECT COUNT(*) AS c FROM risks WHERE risk_score >= 13").fetchone()["c"]
    medium = conn.execute("SELECT COUNT(*) AS c FROM risks WHERE risk_score BETWEEN 6 AND 12").fetchone()["c"]
    low    = conn.execute("SELECT COUNT(*) AS c FROM risks WHERE risk_score <= 5").fetchone()["c"]
    by_level  = [dict(r) for r in conn.execute(
        "SELECT level, COUNT(*) AS c FROM risks GROUP BY level").fetchall()]
    by_status = [dict(r) for r in conn.execute(
        "SELECT status, COUNT(*) AS c FROM risks GROUP BY status").fetchall()]
    recent = [_risk_row(r) for r in conn.execute(
        "SELECT * FROM risks ORDER BY created_date DESC LIMIT 5").fetchall()]
    conn.close()
    return jsonify(total=total, high=high, medium=medium, low=low,
                   by_level=by_level, by_status=by_status, recent=recent)


@risk_register_bp.route("/api/risks", methods=["GET"])
def list_risks():
    level  = request.args.get("level", "")
    entity = request.args.get("entity", "")
    status = request.args.get("status", "")
    cat    = request.args.get("category", "")

    conn = get_db()
    q, p = "SELECT * FROM risks WHERE 1=1", []
    if level:  q += " AND level = ?";           p.append(level)
    if entity: q += " AND entity_name LIKE ?";  p.append(f"%{entity}%")
    if status: q += " AND status = ?";          p.append(status)
    if cat:    q += " AND category = ?";        p.append(cat)
    q += " ORDER BY risk_score DESC, created_date DESC"
    risks = [_risk_row(r) for r in conn.execute(q, p).fetchall()]
    conn.close()
    return jsonify(risks)


@risk_register_bp.route("/api/risks", methods=["POST"])
def create_risk():
    data = request.get_json(force=True)
    conn = get_db()
    now   = datetime.utcnow().isoformat()
    level = data.get("level", "event")
    rid   = _next_risk_id(level, conn)
    l, i  = int(data.get("likelihood", 1)), int(data.get("impact", 1))

    conn.execute("""
        INSERT INTO risks
          (risk_id,level,entity_name,category,title,description,ai_correlation,
           likelihood,impact,risk_score,velocity,mitigation,contingency,
           owner,reviewer,kri,kri_threshold,status,source,parent_risk_id,
           created_date,updated_date,event_context)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (rid, level,
          data.get("entity_name",""), data.get("category",""),
          data.get("title",""), data.get("description",""),
          data.get("ai_correlation",""),
          l, i, l * i,
          data.get("velocity","Short-term"),
          data.get("mitigation",""), data.get("contingency",""),
          data.get("owner",""), data.get("reviewer",""),
          data.get("kri",""), data.get("kri_threshold",""),
          data.get("status","Open"), data.get("source","Manual"),
          data.get("parent_risk_id",""),
          now, now,
          json.dumps(data.get("event_context",{}))))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    risk = _risk_row(conn.execute("SELECT * FROM risks WHERE id=?", (new_id,)).fetchone())
    conn.close()
    return jsonify(risk), 201


@risk_register_bp.route("/api/risks/<int:rid>", methods=["PUT"])
def update_risk(rid):
    data = request.get_json(force=True)
    conn = get_db()
    now  = datetime.utcnow().isoformat()

    fields = ["entity_name","category","title","description","ai_correlation",
              "likelihood","impact","velocity","mitigation","contingency",
              "owner","reviewer","kri","kri_threshold","status","parent_risk_id"]
    sets, params = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f} = ?")
            params.append(data[f])

    # recalc score
    row = dict(conn.execute("SELECT likelihood,impact FROM risks WHERE id=?", (rid,)).fetchone())
    l = int(data.get("likelihood", row["likelihood"]))
    i = int(data.get("impact",     row["impact"]))
    sets.append("risk_score = ?"); params.append(l * i)
    sets.append("updated_date = ?"); params.append(now)
    params.append(rid)

    conn.execute(f"UPDATE risks SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    risk = _risk_row(conn.execute("SELECT * FROM risks WHERE id=?", (rid,)).fetchone())
    conn.close()
    return jsonify(risk)


@risk_register_bp.route("/api/risks/<int:rid>", methods=["DELETE"])
def delete_risk(rid):
    conn = get_db()
    conn.execute("DELETE FROM risks WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify(deleted=True)


@risk_register_bp.route("/api/risks/generate", methods=["POST"])
def generate_risks():
    data        = request.get_json(force=True)
    level       = data.get("level", "event")
    entity_name = data.get("entity_name", "")
    context     = data.get("context", {})

    if not ANTHROPIC_API_KEY:
        return jsonify(error="ANTHROPIC_API_KEY not configured"), 500

    level_desc = {
        "enterprise": "DCT enterprise-wide strategic and operational risks",
        "affiliate":  f"risks specific to the affiliate organisation '{entity_name}'",
        "department": f"risks for the '{entity_name}' department within DCT",
        "event":      f"risks for the event '{entity_name}'",
    }.get(level, "operational risks")

    ctx_text = ""
    if context:
        ctx_text = "\n".join(f"{k}: {v}" for k, v in context.items() if v)

    prompt = f"""You are a senior risk analyst for the Department of Culture and Tourism (DCT), Abu Dhabi.
Generate a formal risk register for {level_desc}.

{f'Event/Entity context:{chr(10)}{ctx_text}' if ctx_text else ''}

Produce exactly 9 risks covering a diverse range of categories:
Strategic, Operational, Financial, Reputational, Safety, Compliance,
Environmental, Security, and Crowd/Audience Management (where applicable).

For each risk:
- category:       One of the categories above
- title:          Short (5-8 word) risk title
- description:    2-3 sentences describing the risk and its potential consequences
- ai_correlation: 1-2 sentences explaining how this risk correlates with or escalates other risks in the register
- likelihood:     Integer 1-5 (1=Rare, 5=Almost Certain)
- impact:         Integer 1-5 (1=Negligible, 5=Catastrophic)
- velocity:       One of: Immediate | Short-term | Long-term
- mitigation:     2-3 sentences of specific, actionable preventive measures
- contingency:    1-2 sentences of response actions if the risk materialises
- owner:          Specific DCT role (e.g. "DCT Events Safety Manager")
- reviewer:       Oversight role (e.g. "DCT Risk & Compliance Director")
- kri:            A measurable Key Risk Indicator
- kri_threshold:  The threshold value that triggers escalation"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        with client.messages.stream(
            model=MODEL_ANALYSIS,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": RISK_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()

        text_block = next(b for b in msg.content if b.type == "text")
        result = json.loads(text_block.text)

        conn  = get_db()
        now   = datetime.utcnow().isoformat()
        saved = []
        for r in result.get("risks", []):
            rid_str = _next_risk_id(level, conn)
            l, i = int(r["likelihood"]), int(r["impact"])
            conn.execute("""
                INSERT INTO risks
                  (risk_id,level,entity_name,category,title,description,ai_correlation,
                   likelihood,impact,risk_score,velocity,mitigation,contingency,
                   owner,reviewer,kri,kri_threshold,status,source,
                   created_date,updated_date,event_context)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (rid_str, level, entity_name,
                  r["category"], r["title"], r["description"], r["ai_correlation"],
                  l, i, l * i, r["velocity"],
                  r["mitigation"], r["contingency"],
                  r["owner"], r["reviewer"],
                  r["kri"], r["kri_threshold"],
                  "Open", "AI-Generated",
                  now, now, json.dumps(context)))
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            saved.append(_risk_row(conn.execute("SELECT * FROM risks WHERE id=?", (new_id,)).fetchone()))
        conn.commit()
        conn.close()
        return jsonify(risks=saved, count=len(saved))

    except StopIteration:
        return jsonify(error="AI returned no response"), 500
    except json.JSONDecodeError as e:
        return jsonify(error=f"JSON parse error: {e}"), 500
    except TypeError as e:
        return jsonify(error=f"API key error: {e}"), 500
    except anthropic.AuthenticationError:
        return jsonify(error="Invalid Anthropic API key"), 401
    except anthropic.APIError as e:
        return jsonify(error=f"Anthropic API error: {e}"), 500
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Unexpected error: {e}"), 500
