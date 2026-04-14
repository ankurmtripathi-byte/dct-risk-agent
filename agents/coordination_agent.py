import json
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from database import get_db

coordination_bp = Blueprint("coordination", __name__)


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
    """Return risks suitable for sharing, grouped by agency sharing level."""
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
    else:  # None
        risks = []

    conn.close()
    return jsonify(risks=risks, sharing_level=sharing)


@coordination_bp.route("/api/coordination/matrix", methods=["GET"])
def coordination_matrix():
    """Summary matrix: agencies x risk categories."""
    conn = get_db()
    agencies = [dict(r) for r in conn.execute("SELECT * FROM agencies ORDER BY name").fetchall()]
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM risks WHERE category != ''"
    ).fetchall()]
    counts = {}
    for cat in cats:
        c = conn.execute(
            "SELECT COUNT(*) AS n FROM risks WHERE category=? AND status != 'Closed'",
            (cat,)
        ).fetchone()["n"]
        counts[cat] = c
    conn.close()
    return jsonify(agencies=agencies, categories=cats, risk_counts=counts)
