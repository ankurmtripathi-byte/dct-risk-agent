import json
import re


def extract_json(text: str):
    """Strip markdown code fences and parse JSON from model output."""
    text = text.strip()
    text = re.sub(r'^```(?:json|JSON)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    return json.loads(text.strip())
