import json
import os

import anthropic
from flask import Flask, jsonify, render_template, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk_id":           {"type": "string"},
                    "category":          {"type": "string"},
                    "description":       {"type": "string"},
                    "likelihood":        {"type": "integer"},
                    "impact":            {"type": "integer"},
                    "risk_score":        {"type": "integer"},
                    "mitigation_action": {"type": "string"},
                    "owner":             {"type": "string"},
                },
                "required": [
                    "risk_id", "category", "description",
                    "likelihood", "impact", "risk_score",
                    "mitigation_action", "owner",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["risks"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a senior risk management specialist for the Department of Culture and Tourism (DCT). "
    "You produce formal, professional risk registers for government events and venues following "
    "ISO 31000 standards. Your assessments are suitable for presentation to senior government "
    "officials and event oversight committees. Be specific, realistic, and context-aware."
)


def risk_level(score: int) -> str:
    if score <= 5:
        return "low"
    if score <= 12:
        return "medium"
    return "high"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = raw.strip()
    return jsonify({
        "api_key_set": bool(key),
        "api_key_length": len(key),
        "api_key_prefix": key[:10] if key else None,
    })


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON payload received."}), 400

    event_name = (data.get("event_name") or "").strip()
    venue      = (data.get("venue")      or "").strip()
    date       = (data.get("date")       or "").strip()
    attendance = (data.get("attendance") or "").strip()
    event_type = (data.get("event_type") or "").strip()

    if not all([event_name, venue, date, attendance, event_type]):
        return jsonify({"error": "All fields are required."}), 400

    try:
        attendance_int = int(attendance)
        if attendance_int < 1:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Expected attendance must be a positive integer."}), 400

    event_type_label = {
        "concert":    "Concert / Live Music",
        "festival":   "Festival / Cultural Festival",
        "exhibition": "Exhibition / Trade Show",
        "sports":     "Sports Event",
        "vip":        "VIP / Diplomatic Event",
    }.get(event_type, event_type.capitalize())

    user_prompt = f"""Generate a formal risk register for the following event:

Event Name:          {event_name}
Venue:               {venue}
Date:                {date}
Expected Attendance: {attendance_int:,}
Event Type:          {event_type_label}

Produce exactly 9 risks that are specific and realistic for this event. Cover a diverse range
of categories such as: Safety, Security, Medical/Health, Operational, Reputational, Financial,
Regulatory/Compliance, Environmental, and Crowd Management.

For each risk:
- risk_id:           Sequential format R001 through R009
- category:          Single descriptive category name
- description:       2–3 professional sentences describing the risk and its potential consequences
- likelihood:        Integer 1–5  (1=Rare  2=Unlikely  3=Possible  4=Likely  5=Almost Certain)
- impact:            Integer 1–5  (1=Negligible  2=Minor  3=Moderate  4=Major  5=Catastrophic)
- risk_score:        Exactly likelihood × impact
- mitigation_action: 2–3 sentences of specific, actionable mitigation measures
- owner:             Specific role/team (e.g. "Event Safety Manager", "DCT Security Directorate")"""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on the server. Add it in Vercel → Settings → Environment Variables."}), 500

    try:
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": RISK_SCHEMA}},
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            final_message = stream.get_final_message()

        text_block = next(b for b in final_message.content if b.type == "text")
        result = json.loads(text_block.text)

        # Guarantee risk_score equals likelihood × impact and annotate level
        for risk in result.get("risks", []):
            risk["risk_score"] = risk["likelihood"] * risk["impact"]
            risk["level"] = risk_level(risk["risk_score"])

        return jsonify(result)

    except StopIteration:
        return jsonify({"error": "The AI returned no text response. Please try again."}), 500
    except json.JSONDecodeError as exc:
        return jsonify({"error": f"Could not parse AI response as JSON: {exc}"}), 500
    except TypeError as exc:
        # SDK raises TypeError when api_key resolves to None at request time
        return jsonify({"error": f"API key configuration error: {exc}"}), 500
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid API key. Check the value in Vercel → Settings → Environment Variables."}), 401
    except anthropic.RateLimitError:
        return jsonify({"error": "API rate limit reached. Please wait a moment and try again."}), 429
    except anthropic.APIError as exc:
        return jsonify({"error": f"Anthropic API error: {exc}"}), 500
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
