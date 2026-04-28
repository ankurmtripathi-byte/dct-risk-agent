import json
import os
import sqlite3
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from config import UPLOAD_FOLDER, MAX_UPLOAD_MB, DB_PATH
from database import init_db
from agents.risk_register_agent import risk_register_bp
from agents.ingestion_agent      import ingestion_bp
from agents.ingestion_agent      import process_document_pipeline as process_document
from agents.news_agent           import (news_bp, fetch_news, analyze_relevance,
                                         map_to_risks, generate_risk_bulletin,
                                         get_refresh_status)
from agents.arc_pack_agent       import arc_pack_bp
from agents.coordination_agent   import coordination_bp, seed_agencies
from seed_demo import seed_demo_data

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'xlsx', 'txt'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"]      = UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.config["TIMEOUT"]            = 120  # 2 minutes max per request

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    init_db()

    from agents.ingestion_agent import seed_sample_documents
    seed_sample_documents(UPLOAD_FOLDER)

    import sqlite3 as _sqlite3
    _seed_conn = _sqlite3.connect(DB_PATH)
    seed_agencies(_seed_conn)
    _seed_conn.close()

    seed_demo_data()

    app.register_blueprint(risk_register_bp)
    app.register_blueprint(ingestion_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(arc_pack_bp)
    app.register_blueprint(coordination_bp)

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/health")
    def health():
        import os as _os
        from config import ANTHROPIC_API_KEY, NEWSAPI_KEY
        key = (ANTHROPIC_API_KEY or "").strip()
        return jsonify(
            status="ok",
            api_key_set=bool(key),
            api_key_prefix=key[:10] if key else None,
            newsapi_key_set=bool(NEWSAPI_KEY),
        )

    return app


app = create_app()


_news_cache = {"items": [], "bulletin": {}, "mapping": {}, "last_run": None}


def run_news_pipeline():
    """Full news pipeline — fetch, score, map, bulletin."""
    print(">> News pipeline starting...")
    conn = sqlite3.connect(DB_PATH)
    try:
        raw     = fetch_news()
        scored  = analyze_relevance(raw)
        mapping = map_to_risks([i for i in scored if i.get('relevance_score', 0) >= 7], conn)
        bulletin = generate_risk_bulletin(scored)

        # Save to DB
        cursor = conn.cursor()
        for item in scored:
            cursor.execute("""
                INSERT OR IGNORE INTO news_items
                (headline, source, url, published_date, fetched_date,
                 relevance_score, mapped_risk_categories, ai_analysis)
                VALUES (?,?,?,?,datetime('now'),?,?,?)
            """, (
                item.get('headline', ''),
                item.get('source', ''),
                item.get('url', ''),
                item.get('published_date', ''),
                item.get('relevance_score', 0),
                json.dumps(item.get('risk_categories', [])),
                item.get('one_line_insight', '')
            ))
        conn.commit()

        _news_cache["items"]    = scored
        _news_cache["bulletin"] = bulletin
        _news_cache["mapping"]  = mapping
        _news_cache["last_run"] = datetime.now().isoformat()
        print(f">> News pipeline done: {len(scored)} scored items")

    except Exception as e:
        print(f">> News pipeline error: {e}")
    finally:
        conn.close()


@app.route('/api/news/fetch', methods=['GET'])
def news_fetch():
    thread = threading.Thread(target=run_news_pipeline)
    thread.daemon = True
    thread.start()
    thread.join(timeout=60)  # Wait max 60s
    return jsonify({
        "items":    _news_cache.get("items", []),
        "bulletin": _news_cache.get("bulletin", {}),
        "mapping":  _news_cache.get("mapping", {}),
        "last_run": _news_cache.get("last_run")
    })


@app.route('/api/news/latest', methods=['GET'])
def news_latest():
    if not _news_cache["items"]:
        run_news_pipeline()
    return jsonify({
        "items":    _news_cache.get("items", []),
        "bulletin": _news_cache.get("bulletin", {}),
        "mapping":  _news_cache.get("mapping", {})
    })


@app.route('/api/news/bulletin', methods=['GET'])
def news_bulletin():
    return jsonify(_news_cache.get("bulletin", {}))


@app.route('/api/news/refresh-status', methods=['GET'])
def news_refresh_status():
    conn = sqlite3.connect(DB_PATH)
    status = get_refresh_status(conn)
    conn.close()
    status["last_run"] = _news_cache.get("last_run", "Never")
    return jsonify(status)


@app.route('/news')
def news_page():
    return render_template('news_monitor.html')


@app.route('/api/ingest/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: PDF, DOCX, XLSX, TXT"}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)
    return jsonify({"message": "Uploaded", "filename": file.filename, "filepath": filepath})


@app.route('/api/ingest/process', methods=['POST'])
def process_doc():
    data = request.get_json()
    filepath = data.get('filepath')
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    conn = sqlite3.connect(DB_PATH)
    try:
        result = process_document(filepath, conn)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/ingest/add-risk', methods=['POST'])
def add_ingested_risk():
    risk = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Auto-generate risk ID using max existing suffix to avoid collisions on deletion
    cursor.execute("""
        SELECT MAX(CAST(SUBSTR(risk_id, 5) AS INTEGER))
        FROM risks WHERE risk_id LIKE 'ING-%'
    """)
    row = cursor.fetchone()
    next_num = (row[0] or 0) + 1
    risk_id = f"ING-{str(next_num).zfill(3)}"

    cursor.execute("""
        INSERT INTO risks (risk_id, level, entity_name, category, title, description,
        likelihood, impact, risk_score, mitigation, owner, status, source, created_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
    """, (
        risk_id, 'event', risk.get('source_doc', 'Ingested Document'),
        risk.get('category', 'Operational'), risk.get('title', ''),
        risk.get('description', ''),
        risk.get('likelihood') or 3, risk.get('impact') or 3,
        (risk.get('likelihood') or 3) * (risk.get('impact') or 3),
        risk.get('mitigation', ''), risk.get('owner', 'TBC'),
        'Open', 'Ingested',
    ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Risk added", "risk_id": risk_id})


@app.route('/api/ingest/documents', methods=['GET'])
def list_ingested_documents():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, filename, doc_type, upload_date,
               processed, extracted_risks_count, summary
        FROM ingested_documents ORDER BY upload_date DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    docs = [{"id": r[0], "filename": r[1], "doc_type": r[2], "upload_date": r[3],
             "processed": r[4], "extracted_risks_count": r[5], "summary": r[6]}
            for r in rows]
    return jsonify(docs)


@app.route('/api/dashboard/stats', methods=['GET'])
def dashboard_stats():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # Core risk counts
    c.execute("SELECT COUNT(*) FROM risks WHERE status != 'Closed'")
    total_active = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM risks WHERE risk_score >= 15 AND status != 'Closed'")
    high_critical = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM risks WHERE risk_score >= 13 AND status != 'Closed'")
    high_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM risks WHERE risk_score BETWEEN 6 AND 12 AND status != 'Closed'")
    medium_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM risks WHERE risk_score <= 5 AND status != 'Closed'")
    low_count = c.fetchone()[0]

    # By level
    c.execute("""
        SELECT level, COUNT(*) as cnt FROM risks
        WHERE status != 'Closed' GROUP BY level ORDER BY cnt DESC
    """)
    by_level = [{"level": r[0], "c": r[1]} for r in c.fetchall()]

    # By status
    c.execute("""
        SELECT status, COUNT(*) as cnt FROM risks GROUP BY status ORDER BY cnt DESC
    """)
    by_status = [{"status": r[0], "c": r[1]} for r in c.fetchall()]

    # Heatmap: likelihood × impact counts (open risks only)
    c.execute("""
        SELECT likelihood, impact, COUNT(*) as cnt FROM risks
        WHERE status != 'Closed' AND likelihood IS NOT NULL AND impact IS NOT NULL
        GROUP BY likelihood, impact
    """)
    heatmap = [{"l": r[0], "i": r[1], "c": r[2]} for r in c.fetchall()]

    # Documents ingested
    c.execute("SELECT COUNT(*) FROM ingested_documents WHERE processed = 1")
    docs_ingested = c.fetchone()[0]

    # News items last 7 days
    c.execute("""
        SELECT COUNT(*) FROM news_items
        WHERE fetched_date >= datetime('now', '-7 days')
    """)
    news_7d = c.fetchone()[0]

    # ARC packs total
    c.execute("SELECT COUNT(*) FROM arc_packs")
    arc_packs = c.fetchone()[0]

    # Recent activity feed — last 10 risks by created_date
    c.execute("""
        SELECT risk_id, title, level, category, risk_score, status, source, created_date
        FROM risks ORDER BY created_date DESC LIMIT 10
    """)
    recent_risks = [
        {"risk_id": r[0], "title": r[1], "level": r[2], "category": r[3],
         "risk_score": r[4], "status": r[5], "source": r[6], "created_date": r[7]}
        for r in c.fetchall()
    ]

    # Intelligence alerts: score >= 20 open risks
    c.execute("""
        SELECT risk_id, title, category, risk_score, status
        FROM risks WHERE risk_score >= 20 AND status != 'Closed'
        ORDER BY risk_score DESC LIMIT 10
    """)
    critical_alerts = [
        {"risk_id": r[0], "title": r[1], "category": r[2],
         "risk_score": r[3], "status": r[4], "type": "critical"}
        for r in c.fetchall()
    ]

    # KRI threshold breaches (risks where kri_threshold set)
    c.execute("""
        SELECT risk_id, title, category, risk_score, kri, kri_threshold
        FROM risks WHERE kri_threshold != '' AND kri_threshold IS NOT NULL
        AND status != 'Closed' LIMIT 5
    """)
    kri_alerts = [
        {"risk_id": r[0], "title": r[1], "category": r[2],
         "risk_score": r[3], "kri": r[4], "kri_threshold": r[5], "type": "kri"}
        for r in c.fetchall()
    ]

    # High-relevance news alerts (score >= 7, last 48h)
    c.execute("""
        SELECT headline, source, relevance_score, fetched_date
        FROM news_items
        WHERE relevance_score >= 7
        AND fetched_date >= datetime('now', '-48 hours')
        ORDER BY relevance_score DESC LIMIT 5
    """)
    news_alerts = [
        {"headline": r[0], "source": r[1], "relevance_score": r[2],
         "fetched_date": r[3], "type": "news"}
        for r in c.fetchall()
    ]

    conn.close()
    return jsonify(
        total_active   = total_active,
        high_critical  = high_critical,
        high           = high_count,
        medium         = medium_count,
        low            = low_count,
        docs_ingested  = docs_ingested,
        news_7d        = news_7d,
        arc_packs      = arc_packs,
        by_level       = by_level,
        by_status      = by_status,
        heatmap        = heatmap,
        recent_risks   = recent_risks,
        alerts         = critical_alerts + kri_alerts + news_alerts,
    )


@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/api/settings', methods=['GET'])
def get_settings():
    from dotenv import dotenv_values
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    vals = dotenv_values(env_path) if os.path.exists(env_path) else {}
    return jsonify(
        anthropic_key_set  = bool(vals.get('ANTHROPIC_API_KEY', '').strip()),
        newsapi_key_set    = bool(vals.get('NEWSAPI_KEY', '').strip()),
        committee_name     = vals.get('COMMITTEE_NAME', 'Audit & Risk Committee'),
        org_name           = vals.get('ORG_NAME', 'Department of Culture and Tourism'),
        default_owner      = vals.get('DEFAULT_OWNER', 'Risk Management Office'),
        anthropic_key_hint = (vals.get('ANTHROPIC_API_KEY', '') or '')[:12] + '…' if vals.get('ANTHROPIC_API_KEY') else '',
        newsapi_key_hint   = (vals.get('NEWSAPI_KEY', '') or '')[:8] + '…' if vals.get('NEWSAPI_KEY') else '',
    )


@app.route('/api/settings', methods=['POST'])
def save_settings():
    data     = request.get_json(force=True) or {}
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

    # Read existing lines preserving comments
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    def _set(key, value):
        nonlocal lines
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}=') or line.startswith(f'{key} ='):
                lines[i] = f'{key}={value}\n'
                found = True
                break
        if not found and value:
            lines.append(f'{key}={value}\n')

    if data.get('anthropic_key') and not data['anthropic_key'].startswith('sk-…'):
        _set('ANTHROPIC_API_KEY', data['anthropic_key'])
    if data.get('newsapi_key') and not data['newsapi_key'].startswith('…'):
        _set('NEWSAPI_KEY', data['newsapi_key'])
    if data.get('committee_name'):
        _set('COMMITTEE_NAME', data['committee_name'])
    if data.get('org_name'):
        _set('ORG_NAME', data['org_name'])
    if data.get('default_owner'):
        _set('DEFAULT_OWNER', data['default_owner'])

    with open(env_path, 'w') as f:
        f.writelines(lines)

    return jsonify(saved=True)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
