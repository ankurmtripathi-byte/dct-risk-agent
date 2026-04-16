import os

from flask import Flask, jsonify, render_template

from config import UPLOAD_FOLDER, MAX_UPLOAD_MB
from database import init_db
from agents.risk_register_agent import risk_register_bp
from agents.ingestion_agent      import ingestion_bp
from agents.news_agent           import news_bp
from agents.arc_pack_agent       import arc_pack_bp
from agents.coordination_agent   import coordination_bp


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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
