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

    # Auto-generate risk ID
    cursor.execute("SELECT COUNT(*) FROM risks WHERE source='Ingested'")
    count = cursor.fetchone()[0] + 1
    risk_id = f"ING-{str(count).zfill(3)}"

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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
