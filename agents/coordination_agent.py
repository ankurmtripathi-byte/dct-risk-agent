import json
from datetime import datetime

import anthropic
from flask import Blueprint, jsonify, render_template, request

from utils import extract_json as _extract_json

import config
from config import ANTHROPIC_API_KEY, MODEL_FAST
from database import get_db

coordination_bp = Blueprint("coordination", __name__)

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Constants ─────────────────────────────────────────────────────────────────

SEED_AGENCIES = [
    {"name": "Abu Dhabi Police",          "type": "Government", "risk_sharing_level": "Full",    "mandate": "Public safety, security, crowd management, law enforcement"},
    {"name": "NCEMA",                     "type": "Government", "risk_sharing_level": "Full",    "mandate": "National crisis and emergency management, business continuity"},
    {"name": "HAAD",                      "type": "Regulator",  "risk_sharing_level": "Summary", "mandate": "Health regulation, public health oversight, medical services licensing"},
    {"name": "SEHA",                      "type": "Government", "risk_sharing_level": "Summary", "mandate": "Healthcare delivery, medical services, emergency health response"},
    {"name": "EAD",                       "type": "Regulator",  "risk_sharing_level": "Summary", "mandate": "Environmental protection, sustainability, ecological risk"},
    {"name": "ADAC",                      "type": "Government", "risk_sharing_level": "Summary", "mandate": "Abu Dhabi airports, aviation infrastructure, airspace management"},
    {"name": "Abu Dhabi Municipality",    "type": "Government", "risk_sharing_level": "Full",    "mandate": "Venue permits, event licensing, public space management, infrastructure"},
    {"name": "Abu Dhabi Executive Office","type": "Government", "risk_sharing_level": "Full",    "mandate": "Government strategy, budget, procurement, inter-agency coordination"},
    {"name": "Musanada",                  "type": "Government", "risk_sharing_level": "Summary", "mandate": "Government facilities management, infrastructure projects, construction"},
]

# Rule-based category → agency mapping (used for fast matrix rendering)
CATEGORY_AGENCY_MAP = {
    "Safety":                  ["Abu Dhabi Police", "NCEMA"],
    "Safety & Security":       ["Abu Dhabi Police", "NCEMA"],
    "Security":                ["Abu Dhabi Police", "NCEMA"],
    "Crowd Management":        ["Abu Dhabi Police", "NCEMA", "Abu Dhabi Municipality"],
    "Health":                  ["HAAD", "SEHA"],
    "Environmental & Health":  ["EAD", "HAAD", "SEHA"],
    "Environmental":           ["EAD"],
    "Financial":               ["Abu Dhabi Executive Office"],
    "Procurement":             ["Abu Dhabi Executive Office"],
    "Compliance":              ["Abu Dhabi Executive Office", "Abu Dhabi Municipality"],
    "Compliance & Regulatory": ["Abu Dhabi Executive Office", "Abu Dhabi Municipality"],
    "Infrastructure":          ["ADAC", "Musanada", "Abu Dhabi Municipality"],
    "Operational":             ["ADAC", "Musanada", "Abu Dhabi Municipality"],
    "Strategic":               ["Abu Dhabi Executive Office"],
    "Reputational":            ["Abu Dhabi Executive Office"],
}

# Canonical display categories for the matrix columns
MATRIX_CATEGORIES = [
    "Safety & Security",
    "Operational",
    "Financial",
    "Compliance & Regulatory",
    "Environmental & Health",
    "Strategic",
]


# ── Seeding ───────────────────────────────────────────────────────────────────

def seed_agencies(db_connection):
    """Insert default partner agencies if not already present (by name)."""
    cursor = db_connection.cursor()
    existing = {r[0] for r in cursor.execute("SELECT name FROM agencies").fetchall()}
    added = 0
    for ag in SEED_AGENCIES:
        if ag["name"] not in existing:
            cursor.execute("""
                INSERT INTO agencies (name, type, contact_name, contact_email, risk_sharing_level)
                VALUES (?,?,?,?,?)
            """, (ag["name"], ag["type"], "", "", ag["risk_sharing_level"]))
            added += 1
    if added:
        db_connection.commit()
        print(f">> Coordination: seeded {added} partner agencies")


# ── Pipeline Functions ────────────────────────────────────────────────────────

def generate_agency_risk_brief(agency_id, risk_ids, db_connection):
    """Generate a risk brief tailored for the given agency.

    Rephrases risks in agency-appropriate language, removes internal DCT
    references, and highlights risks most relevant to the agency's mandate.
    Returns: dict {agency, brief_text, risks_included, generated_at}
    """
    cursor = db_connection.cursor()

    # Fetch agency
    cursor.execute("SELECT * FROM agencies WHERE id=?", (agency_id,))
    row = cursor.fetchone()
    if not row:
        return {"error": f"Agency {agency_id} not found"}
    agency = dict(row)

    # Fetch risks
    placeholders = ",".join("?" * len(risk_ids))
    cursor.execute(
        f"SELECT * FROM risks WHERE id IN ({placeholders}) AND status != 'Closed'",
        risk_ids
    )
    risks = [dict(r) for r in cursor.fetchall()]
    if not risks:
        return {"error": "No valid open risks found for the provided IDs"}

    # Get agency mandate from seed data (fallback to type)
    mandate = next(
        (a["mandate"] for a in SEED_AGENCIES if a["name"] == agency["name"]),
        f"{agency.get('type','Government')} agency"
    )

    risks_text = "\n".join([
        f"- [{r['risk_id']}] {r['title']} | Category: {r['category']} | "
        f"Score: {r['risk_score']} | Likelihood: {r['likelihood']} | "
        f"Impact: {r['impact']} | Status: {r['status']}\n"
        f"  Description: {r['description']}\n"
        f"  Mitigation: {r['mitigation']}"
        for r in risks
    ])

    prompt = f"""You are DCT Abu Dhabi's risk coordination officer preparing a risk brief for an external partner agency.

RECIPIENT AGENCY: {agency['name']}
AGENCY TYPE: {agency.get('type','Government')}
AGENCY MANDATE: {mandate}
RISK SHARING LEVEL: {agency.get('risk_sharing_level','Summary')}

RISKS TO BRIEF ({len(risks)} risks):
{risks_text}

Write a professional inter-agency risk brief following these rules:
1. Remove all internal DCT risk IDs, internal ownership names, and budget figures
2. Use language appropriate for {agency['name']} — emphasise risks relevant to their mandate
3. Deprioritise or omit risks with no relevance to this agency's mandate
4. Use formal UAE government communication style
5. Structure the brief as:

---
RISK INTELLIGENCE BRIEF
To: {agency['name']}
From: Department of Culture and Tourism — Risk Management Office
Date: {datetime.now().strftime('%d %B %Y')}
Classification: OFFICIAL

EXECUTIVE SUMMARY
[2-3 sentences on the overall risk picture relevant to {agency['name']}]

KEY RISKS REQUIRING YOUR AWARENESS
[For each relevant risk: Risk Title, Situation, Why it matters to {agency['name']}, Suggested coordination action]

COORDINATION REQUESTED
[Specific asks from {agency['name']} — be concrete]

NEXT STEPS
[2-3 bullet points]
---

Write the full brief now."""

    resp = client.messages.create(
        model=MODEL_FAST,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "agency":         agency["name"],
        "agency_id":      agency_id,
        "brief_text":     resp.content[0].text.strip(),
        "risks_included": len(risks),
        "generated_at":   datetime.now().isoformat(),
    }


def generate_inter_agency_memo(risk_id, agency_id, db_connection):
    """Generate a formal inter-agency memo for a specific risk.

    Format: To / From / Subject / Risk Summary / DCT's Position /
    Requested Action / Response Required By.
    Returns: dict {memo_text, risk_title, agency, generated_at}
    """
    cursor = db_connection.cursor()

    cursor.execute("SELECT * FROM risks WHERE id=?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return {"error": f"Risk {risk_id} not found"}
    risk = dict(row)

    cursor.execute("SELECT * FROM agencies WHERE id=?", (agency_id,))
    row = cursor.fetchone()
    if not row:
        return {"error": f"Agency {agency_id} not found"}
    agency = dict(row)

    mandate = next(
        (a["mandate"] for a in SEED_AGENCIES if a["name"] == agency["name"]),
        agency.get("type", "Government")
    )

    prompt = f"""You are DCT Abu Dhabi's Chief Risk Officer drafting a formal inter-agency memo.

MEMO DETAILS:
Risk Title: {risk['title']}
Risk Category: {risk['category']}
Risk Score: {risk['risk_score']} (Likelihood {risk['likelihood']} × Impact {risk['impact']})
Risk Description: {risk['description']}
Current Status: {risk['status']}
Current Mitigation: {risk.get('mitigation','')}

RECIPIENT: {agency['name']}
RECIPIENT MANDATE: {mandate}

Write a formal UAE government inter-agency memo. Use EXACTLY this structure:

MEMORANDUM

TO:       {agency['name']}
FROM:     H.E. / Risk Management Office, Department of Culture and Tourism
DATE:     {datetime.now().strftime('%d %B %Y')}
REF:      DCT/RISK/{risk['risk_id']}/{datetime.now().strftime('%Y')}
SUBJECT:  [Concise subject line referencing the risk topic]

1. BACKGROUND
[2-3 sentences on the risk context, written for {agency['name']}. Remove internal DCT scoring details.]

2. RISK SUMMARY
[Clear statement of the risk, its likelihood, potential impact relevant to {agency['name']}'s mandate.]

3. DCT'S POSITION
[What DCT is doing about this risk, without internal budget or ownership details.]

4. REQUESTED ACTION
[Specific, numbered list of what DCT requests from {agency['name']}. Be precise and actionable.]

5. RESPONSE REQUIRED BY
[Propose a reasonable response date — 7–14 business days from today.]

6. POINT OF CONTACT
[Generic: DCT Risk Management Office — risk@dct.gov.ae]

Write the full memo now in formal government English."""

    resp = client.messages.create(
        model=MODEL_FAST,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "memo_text":    resp.content[0].text.strip(),
        "risk_title":   risk["title"],
        "risk_id":      risk["risk_id"],
        "agency":       agency["name"],
        "generated_at": datetime.now().isoformat(),
    }


def identify_shared_risks(agency_list, db_connection):
    """Use Claude to identify which open risks are relevant to each agency.

    Returns: dict {agency_name: [{"risk_id": str, "title": str, "reason": str}]}
    """
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT id, risk_id, title, category, description, risk_score "
        "FROM risks WHERE status != 'Closed' ORDER BY risk_score DESC LIMIT 40"
    )
    risks = [dict(r) for r in cursor.fetchall()]
    if not risks:
        return {ag["name"]: [] for ag in agency_list}

    risks_text = "\n".join([
        f"{r['risk_id']}: [{r['category']}] {r['title']} (score {r['risk_score']})"
        for r in risks
    ])
    agencies_text = "\n".join([
        f"- {ag['name']}: {next((s['mandate'] for s in SEED_AGENCIES if s['name']==ag['name']), ag.get('type',''))}"
        for ag in agency_list
    ])

    try:
        resp = client.messages.create(
            model=MODEL_FAST,
            max_tokens=2500,
            messages=[{"role": "user", "content": f"""You are a risk coordination officer. Map DCT risks to the agencies that need to be aware of them.

AGENCIES AND THEIR MANDATES:
{agencies_text}

OPEN DCT RISKS:
{risks_text}

For each agency, list the risk IDs that are relevant to their mandate. Only include risks where the agency has a genuine coordination role.

Return ONLY valid JSON:
{{
  "agency_name_1": [
    {{"risk_id": "EVT-001", "title": "Risk title", "reason": "one sentence why relevant"}}
  ],
  "agency_name_2": [...]
}}

Include ALL agencies in the response, even with empty arrays if no risks apply. JSON only."""}]
        )
        return _extract_json(resp.content[0].text)

    except Exception as e:
        print(f">> identify_shared_risks error: {e}")
        # Rule-based fallback
        result = {ag["name"]: [] for ag in agency_list}
        for risk in risks:
            cat = risk["category"]
            for agency_name in CATEGORY_AGENCY_MAP.get(cat, []):
                if agency_name in result:
                    result[agency_name].append({
                        "risk_id": risk["risk_id"],
                        "title":   risk["title"],
                        "reason":  f"Category '{cat}' falls under this agency's mandate."
                    })
        return result


# ── Routes ────────────────────────────────────────────────────────────────────

@coordination_bp.route("/coordination")
def coordination_page():
    return render_template("coordination.html")


@coordination_bp.route("/api/agencies", methods=["GET"])
def list_agencies():
    conn = get_db()
    agencies = [dict(r) for r in conn.execute(
        "SELECT * FROM agencies ORDER BY type, name"
    ).fetchall()]
    conn.close()
    return jsonify(agencies)


@coordination_bp.route("/api/agencies", methods=["POST"])
def create_agency():
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute("""
        INSERT INTO agencies (name, type, contact_name, contact_email, risk_sharing_level)
        VALUES (?,?,?,?,?)
    """, (
        data.get("name", ""),
        data.get("type", "External"),
        data.get("contact_name", ""),
        data.get("contact_email", ""),
        data.get("risk_sharing_level", "Summary"),
    ))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    agency = dict(conn.execute("SELECT * FROM agencies WHERE id=?", (new_id,)).fetchone())
    conn.close()
    return jsonify(agency), 201


@coordination_bp.route("/api/agencies/<int:agency_id>", methods=["PUT"])
def update_agency(agency_id):
    data = request.get_json(force=True)
    conn = get_db()
    fields = ["name", "type", "contact_name", "contact_email", "risk_sharing_level"]
    sets, params = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f} = ?")
            params.append(data[f])
    if not sets:
        conn.close()
        return jsonify(error="No fields to update"), 400
    params.append(agency_id)
    conn.execute(f"UPDATE agencies SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    agency = dict(conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone())
    conn.close()
    return jsonify(agency)


@coordination_bp.route("/api/agencies/<int:agency_id>", methods=["DELETE"])
def delete_agency(agency_id):
    conn = get_db()
    conn.execute("DELETE FROM agencies WHERE id=?", (agency_id,))
    conn.commit()
    conn.close()
    return jsonify(deleted=True)


@coordination_bp.route("/api/coordination/shared-risks", methods=["GET"])
def shared_risks():
    agency_id = request.args.get("agency_id")
    conn = get_db()

    if agency_id:
        agency = conn.execute("SELECT * FROM agencies WHERE id=?", (agency_id,)).fetchone()
        if not agency:
            conn.close()
            return jsonify(error="Agency not found"), 404
        agency = dict(agency)
        sharing = agency.get("risk_sharing_level", "Summary")
    else:
        sharing = "Summary"

    if sharing == "Full":
        risks = [dict(r) for r in conn.execute(
            "SELECT * FROM risks WHERE status != 'Closed' ORDER BY risk_score DESC"
        ).fetchall()]
    elif sharing == "Summary":
        risks = [dict(r) for r in conn.execute(
            "SELECT id,risk_id,level,category,title,risk_score,status,owner "
            "FROM risks WHERE status != 'Closed' ORDER BY risk_score DESC"
        ).fetchall()]
    else:
        risks = []

    conn.close()
    return jsonify(risks=risks, sharing_level=sharing)


@coordination_bp.route("/api/coordination/matrix", methods=["GET"])
def coordination_matrix():
    """Matrix: agency rows × category columns, cells = relevant risk count."""
    conn = get_db()
    agencies = [dict(r) for r in conn.execute(
        "SELECT * FROM agencies ORDER BY name"
    ).fetchall()]

    # Count risks per canonical category
    cat_counts = {}
    for cat in MATRIX_CATEGORIES:
        # Match both exact and related category names
        related = [c for c, agencies_for_cat in CATEGORY_AGENCY_MAP.items()
                   if cat in c or c in cat]
        related = list(set(related + [cat]))
        placeholders = ",".join("?" * len(related))
        row = conn.execute(
            f"SELECT COUNT(*) FROM risks WHERE category IN ({placeholders}) AND status != 'Closed'",
            related
        ).fetchone()
        cat_counts[cat] = row[0]

    # Build per-agency category counts using rule-based mapping
    agency_matrix = {}
    for ag in agencies:
        if ag.get("risk_sharing_level") == "None":
            agency_matrix[ag["id"]] = {cat: 0 for cat in MATRIX_CATEGORIES}
            continue
        row_counts = {}
        for cat in MATRIX_CATEGORIES:
            # Find which raw categories map to this canonical cat
            relevant_raw = [
                raw for raw, mapped_agencies in CATEGORY_AGENCY_MAP.items()
                if ag["name"] in mapped_agencies and (cat in raw or raw in cat or raw == cat)
            ]
            if not relevant_raw:
                row_counts[cat] = 0
                continue
            placeholders = ",".join("?" * len(relevant_raw))
            count = conn.execute(
                f"SELECT COUNT(*) FROM risks WHERE category IN ({placeholders}) AND status != 'Closed'",
                relevant_raw
            ).fetchone()[0]
            row_counts[cat] = count
        agency_matrix[ag["id"]] = row_counts

    # Total open risks shared with each agency
    for ag in agencies:
        total = sum(agency_matrix.get(ag["id"], {}).values())
        ag["shared_risk_count"] = total

    conn.close()
    return jsonify(
        agencies=agencies,
        categories=MATRIX_CATEGORIES,
        matrix=agency_matrix,
    )


@coordination_bp.route("/api/coordination/brief", methods=["POST"])
def api_generate_brief():
    if not ANTHROPIC_API_KEY:
        return jsonify(error="ANTHROPIC_API_KEY not configured"), 500
    data      = request.get_json(force=True) or {}
    agency_id = data.get("agency_id")
    risk_ids  = data.get("risk_ids", [])
    if not agency_id or not risk_ids:
        return jsonify(error="agency_id and risk_ids are required"), 400
    conn = get_db()
    try:
        result = generate_agency_risk_brief(int(agency_id), [int(i) for i in risk_ids], conn)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except anthropic.AuthenticationError:
        return jsonify(error="Invalid Anthropic API key"), 401
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


@coordination_bp.route("/api/coordination/memo", methods=["POST"])
def api_generate_memo():
    if not ANTHROPIC_API_KEY:
        return jsonify(error="ANTHROPIC_API_KEY not configured"), 500
    data      = request.get_json(force=True) or {}
    risk_id   = data.get("risk_id")
    agency_id = data.get("agency_id")
    if not risk_id or not agency_id:
        return jsonify(error="risk_id and agency_id are required"), 400
    conn = get_db()
    try:
        result = generate_inter_agency_memo(int(risk_id), int(agency_id), conn)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except anthropic.AuthenticationError:
        return jsonify(error="Invalid Anthropic API key"), 401
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        conn.close()


@coordination_bp.route("/api/coordination/identify-shared", methods=["POST"])
def api_identify_shared():
    """Run Claude-powered shared risk identification across all agencies."""
    conn = get_db()
    try:
        agencies = [dict(r) for r in conn.execute("SELECT * FROM agencies").fetchall()]
        result   = identify_shared_risks(agencies, conn)
        return jsonify(result)
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        conn.close()
