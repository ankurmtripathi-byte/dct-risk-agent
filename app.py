import os
import sqlite3

from flask import Flask, jsonify, render_template, request

from config import UPLOAD_FOLDER, MAX_UPLOAD_MB, DB_PATH
from database import init_db
from agents.risk_register_agent import risk_register_bp
from agents.ingestion_agent      import ingestion_bp
from agents.ingestion_agent      import process_document_pipeline as process_document
from agents.news_agent           import news_bp
from agents.arc_pack_agent       import arc_pack_bp
from agents.coordination_agent   import coordination_bp

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
