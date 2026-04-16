import json
import os
from datetime import datetime, timedelta

import anthropic
import requests
from flask import Blueprint, jsonify, render_template, request

import config
from config import ANTHROPIC_API_KEY, MODEL_FAST, NEWSAPI_KEY
from database import get_db

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

news_bp = Blueprint("news", __name__)

NEWSAPI_URL    = "https://newsapi.org/v2/everything"
CURATED_URL    = "https://actually-relevant-api.onrender.com/api/stories"
DCT_QUERY   = (
    "(\"Abu Dhabi\" OR UAE OR tourism OR \"cultural event\") AND "
    "(risk OR safety OR security OR incident OR disruption OR "
    "protest OR weather OR cyber OR fraud OR accident)"
)


# ── Routes ────────────────────────────────────────────────────────────────────

@news_bp.route("/news-monitor")
def news_page():
    return render_template("news_monitor.html")


@news_bp.route("/api/news", methods=["GET"])
def list_news():
    conn = get_db()
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM news_items ORDER BY fetched_date DESC LIMIT 100"
    ).fetchall()]
    for it in items:
        try:
            it["mapped_risk_categories"] = json.loads(it.get("mapped_risk_categories") or "[]")
        except (ValueError, TypeError):
            it["mapped_risk_categories"] = []
    conn.close()
    return jsonify(items)


@news_bp.route("/api/news/fetch", methods=["POST"])
def api_fetch_news():
    if not NEWSAPI_KEY:
        return jsonify(error="NEWSAPI_KEY not configured. Add it in Vercel → Settings → Environment Variables."), 500

    data    = request.get_json(force=True) or {}
    query   = data.get("query", DCT_QUERY)
    page_sz = min(int(data.get("page_size", 20)), 50)

    try:
        resp = requests.get(NEWSAPI_URL, params={
            "q":        query,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": page_sz,
            "apiKey":   NEWSAPI_KEY,
        }, timeout=15)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except requests.RequestException as e:
        return jsonify(error=f"NewsAPI request failed: {e}"), 502

    now  = datetime.utcnow().isoformat()
    conn = get_db()
    saved = 0
    for art in articles:
        url = art.get("url", "")
        if conn.execute("SELECT 1 FROM news_items WHERE url=?", (url,)).fetchone():
            continue
        conn.execute("""
            INSERT INTO news_items
              (headline, source, url, published_date, fetched_date,
               relevance_score, mapped_risk_categories, ai_analysis)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            art.get("title",""),
            (art.get("source") or {}).get("name",""),
            url,
            art.get("publishedAt",""),
            now,
            0, "[]", "",
        ))
        saved += 1
    conn.commit()
    conn.close()
    return jsonify(fetched=len(articles), new=saved)


@news_bp.route("/api/news/curated", methods=["POST"])
def fetch_curated():
    """Fetch today's curated stories from actually-relevant-api.onrender.com."""
    try:
        resp = requests.get(CURATED_URL, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        return jsonify(error=f"Curated stories request failed: {e}"), 502
    except ValueError as e:
        return jsonify(error=f"Invalid JSON from curated API: {e}"), 502

    # Normalise: accept a top-level list OR an object with a list under any key
    stories: list = []
    if isinstance(payload, list):
        stories = payload
    elif isinstance(payload, dict):
        # Try common wrapper keys; fall back to first list value found
        for key in ("stories", "articles", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                stories = payload[key]
                break
        if not stories:
            for val in payload.values():
                if isinstance(val, list):
                    stories = val
                    break

    now  = datetime.utcnow().isoformat()
    conn = get_db()
    saved = 0

    for s in stories:
        if not isinstance(s, dict):
            continue

        # Accept multiple field-name conventions
        headline = (
            s.get("title") or s.get("headline") or
            s.get("name")  or s.get("story")    or ""
        ).strip()
        url = (s.get("url") or s.get("link") or s.get("href") or "").strip()
        source = (
            s.get("source") or s.get("publisher") or
            s.get("outlet") or "actually-relevant-api"
        )
        if isinstance(source, dict):
            source = source.get("name") or source.get("id") or "actually-relevant-api"
        published = (
            s.get("publishedAt") or s.get("published_at") or
            s.get("date")        or s.get("created_at")   or ""
        )

        if not headline:
            continue

        # Deduplicate by URL if present, else by headline
        dup_check = (
            conn.execute("SELECT 1 FROM news_items WHERE url=?", (url,)).fetchone()
            if url else
            conn.execute("SELECT 1 FROM news_items WHERE headline=?", (headline,)).fetchone()
        )
        if dup_check:
            continue

        conn.execute("""
            INSERT INTO news_items
              (headline, source, url, published_date, fetched_date,
               relevance_score, mapped_risk_categories, ai_analysis)
            VALUES (?,?,?,?,?,?,?,?)
        """, (headline, str(source), url, published, now, 0, "[]", ""))
        saved += 1

    conn.commit()
    conn.close()
    return jsonify(fetched=len(stories), new=saved)


@news_bp.route("/api/news/<int:item_id>/analyse", methods=["POST"])
def analyse_news_item(item_id):
    if not ANTHROPIC_API_KEY:
        return jsonify(error="ANTHROPIC_API_KEY not configured"), 500

    conn  = get_db()
    item  = conn.execute("SELECT * FROM news_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return jsonify(error="News item not found"), 404
    item = dict(item)

    prompt = f"""You are a DCT risk analyst. Assess this news headline for relevance to the Department of Culture and Tourism, Abu Dhabi.

Headline: {item['headline']}
Source: {item['source']}
Published: {item['published_date']}

Return JSON:
{{
  "relevance_score": <integer 1-10, where 10 is highly relevant to DCT risk>,
  "mapped_risk_categories": ["Safety","Security",...],
  "ai_analysis": "<2-3 sentences explaining how this news relates to DCT risks and what action may be needed>"
}}

Risk categories to choose from: Safety, Security, Financial, Reputational,
Operational, Compliance, Environmental, Strategic, Crowd Management"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=MODEL_FAST,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")]
        result = json.loads(raw)

        score    = int(result.get("relevance_score", 5))
        cats     = result.get("mapped_risk_categories", [])
        analysis = result.get("ai_analysis", "")

        conn.execute("""
            UPDATE news_items
            SET relevance_score=?, mapped_risk_categories=?, ai_analysis=?
            WHERE id=?
        """, (score, json.dumps(cats), analysis, item_id))
        conn.commit()
        conn.close()
        return jsonify(relevance_score=score,
                       mapped_risk_categories=cats,
                       ai_analysis=analysis)

    except json.JSONDecodeError as e:
        conn.close()
        return jsonify(error=f"JSON parse error: {e}"), 500
    except TypeError as e:
        conn.close()
        return jsonify(error=f"API key error: {e}"), 500
    except anthropic.AuthenticationError:
        conn.close()
        return jsonify(error="Invalid Anthropic API key"), 401
    except Exception as e:  # noqa: BLE001
        conn.close()
        return jsonify(error=f"Unexpected error: {e}"), 500


@news_bp.route("/api/news/<int:item_id>/create-risk", methods=["POST"])
def create_risk_from_news(item_id):
    conn  = get_db()
    item  = conn.execute("SELECT * FROM news_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return jsonify(error="News item not found"), 404
    item = dict(item)

    from agents.risk_register_agent import _next_risk_id
    now     = datetime.utcnow().isoformat()
    rid_str = _next_risk_id("enterprise", conn)
    cats    = []
    try:
        cats = json.loads(item.get("mapped_risk_categories") or "[]")
    except (ValueError, TypeError):
        pass
    category = cats[0] if cats else "Operational"

    conn.execute("""
        INSERT INTO risks
          (risk_id,level,entity_name,category,title,description,
           likelihood,impact,risk_score,status,source,created_date,updated_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (rid_str, "enterprise", "DCT Enterprise",
          category,
          f"News-Triggered: {item['headline'][:80]}",
          f"Risk identified from news monitoring. {item.get('ai_analysis','')}",
          3, 3, 9, "Open", "News-Triggered", now, now))
    conn.execute("UPDATE news_items SET triggered_risk_id=? WHERE id=?", (rid_str, item_id))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return jsonify(risk_id=rid_str, db_id=new_id), 201


@news_bp.route("/api/news/<int:item_id>", methods=["DELETE"])
def delete_news_item(item_id):
    conn = get_db()
    conn.execute("DELETE FROM news_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify(deleted=True)


# ── Pipeline utility functions (stubs — logic to be implemented) ──────────────

DEFAULT_TOPICS = [
    "Abu Dhabi events",
    "UAE crowd safety",
    "Abu Dhabi weather",
    "UAE tourism",
    "Abu Dhabi concerts festivals",
    "UAE regulatory compliance",
    "Abu Dhabi security",
    "UAE aviation disruption",
    "Abu Dhabi infrastructure construction",
    "Middle East political stability"
]

SYNTHETIC_NEWS = [
    {
        "headline": "Etihad Airways cancels 12 flights due to operational disruption",
        "source": "The National",
        "url": "https://www.thenationalnews.com",
        "description": "Etihad Airways announced cancellation of 12 routes this weekend citing crew availability issues, affecting an estimated 4,200 passengers.",
        "published_date": (datetime.now() - timedelta(hours=6)).isoformat(),
        "demo": True
    },
    {
        "headline": "UAE issues heat advisory — temperatures to exceed 46°C across Abu Dhabi",
        "source": "WAM News Agency",
        "url": "https://wam.ae",
        "description": "The National Centre of Meteorology has issued a Level 2 heat advisory for Abu Dhabi emirate. Outdoor gatherings of over 500 people advised to have cooling stations.",
        "published_date": (datetime.now() - timedelta(hours=3)).isoformat(),
        "demo": True
    },
    {
        "headline": "Abu Dhabi Police issue new crowd management guidelines for large events",
        "source": "Gulf News",
        "url": "https://gulfnews.com",
        "description": "Abu Dhabi Police released updated crowd safety regulations requiring events over 10,000 attendees to submit revised security plans 30 days in advance.",
        "published_date": (datetime.now() - timedelta(hours=12)).isoformat(),
        "demo": True
    },
    {
        "headline": "Cyber attack disrupts ticketing systems at major UAE venue",
        "source": "Arabian Business",
        "url": "https://www.arabianbusiness.com",
        "description": "A regional entertainment venue reported a ransomware attack on its online ticketing platform, forcing manual check-in for 8,000 attendees over the weekend.",
        "published_date": (datetime.now() - timedelta(hours=18)).isoformat(),
        "demo": True
    },
    {
        "headline": "UAE Ministry of Economy tightens contractor licensing requirements",
        "source": "Khaleej Times",
        "url": "https://www.khaleejtimes.com",
        "description": "New regulations effective Q2 2026 require all event contractors above AED 500,000 contract value to hold updated federal licensing. Grace period of 90 days granted.",
        "published_date": (datetime.now() - timedelta(hours=24)).isoformat(),
        "demo": True
    },
    {
        "headline": "Massive dust storm forecast for Abu Dhabi — outdoor events at risk",
        "source": "The National",
        "url": "https://www.thenationalnews.com",
        "description": "Meteorologists warn of a severe shamal dust storm expected to hit Abu Dhabi on Thursday and Friday. Visibility may drop below 500m in some areas.",
        "published_date": (datetime.now() - timedelta(hours=2)).isoformat(),
        "demo": True
    },
    {
        "headline": "Abu Dhabi records 14% surge in international tourist arrivals Q1 2026",
        "source": "WAM News Agency",
        "url": "https://wam.ae",
        "description": "DCT Abu Dhabi tourism report shows record-breaking Q1 2026 arrivals, with hotel occupancy at 91%. Major events cited as primary driver.",
        "published_date": (datetime.now() - timedelta(hours=36)).isoformat(),
        "demo": True
    },
    {
        "headline": "Regional geopolitical tensions prompt heightened UAE security posture",
        "source": "Reuters",
        "url": "https://reuters.com",
        "description": "UAE security authorities have elevated threat monitoring protocols following regional developments. Large public gatherings subject to enhanced screening procedures.",
        "published_date": (datetime.now() - timedelta(hours=8)).isoformat(),
        "demo": True
    }
]


def fetch_news(topics_list=None):
    """Fetch news from NewsAPI for DCT-relevant topics.
    Falls back to synthetic demo data if NEWSAPI_KEY not set.
    Returns: list of raw news item dicts"""
    api_key = getattr(config, 'NEWSAPI_KEY', None) or os.environ.get('NEWSAPI_KEY')
    topics = topics_list or DEFAULT_TOPICS

    # Demo fallback
    if not api_key or api_key in ['', 'your-newsapi-key-here']:
        print(">> News Agent: No NEWSAPI_KEY found — using demo data")
        return SYNTHETIC_NEWS

    seen_urls = set()
    all_items = []
    cutoff = (datetime.now() - timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%S')

    for topic in topics[:6]:  # Limit to 6 topics on free tier
        try:
            resp = requests.get(
                'https://newsapi.org/v2/everything',
                params={
                    'q': topic,
                    'from': cutoff,
                    'sortBy': 'publishedAt',
                    'language': 'en',
                    'pageSize': 5,
                    'apiKey': api_key
                },
                timeout=10
            )
            if resp.status_code == 200:
                for article in resp.json().get('articles', []):
                    url = article.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_items.append({
                            "headline": article.get('title', ''),
                            "source": article.get('source', {}).get('name', ''),
                            "url": url,
                            "description": article.get('description', '') or '',
                            "published_date": article.get('publishedAt', ''),
                            "demo": False
                        })
        except Exception as e:
            print(f">> News fetch error for topic '{topic}': {e}")
            continue

    print(f">> News Agent: Fetched {len(all_items)} articles from NewsAPI")
    return all_items if all_items else SYNTHETIC_NEWS


def analyze_relevance(news_items):
    """Score each news item for DCT risk relevance using Claude Haiku.
    Returns: list of scored news items, filtered to relevance >= 4"""
    pass


def map_to_risks(high_relevance_items, db_connection):
    """For items scoring >= 7, map to existing DB risks or flag as new.
    Returns: dict {amplified: [], new_triggered: [], resolved: [], report: str}"""
    pass


def generate_risk_bulletin(analyzed_items):
    """Generate executive intelligence brief using Claude Opus.
    Returns: dict {situation_overview, top_risks, recommended_actions, watch_list}"""
    pass


def get_refresh_status(db_connection):
    """Return last refresh timestamp and item counts from DB.
    Returns: dict {last_refresh, items_last_48h, high_relevance, risks_updated}"""
    pass
