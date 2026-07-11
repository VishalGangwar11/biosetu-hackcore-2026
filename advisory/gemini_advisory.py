"""
BioSetu - Layer 4: Advisory Generation (Gemini)
----------------------------------------------------
Converts the structured field report (readiness score + early warning)
into a short, plain-language, multilingual farmer-facing message.

Requires: pip install google-genai
API key: set GEMINI_API_KEY in your .env file, or pass directly.

Honesty note: the underlying recommendation is grounded only in the
readiness score / early-warning classification computed in Layer 2/3
(public agronomic reference ranges). This module does NOT invent
specific Syngenta product names or claim proprietary efficacy data —
it explains the *conditions*, not a specific product match, since we
don't have Syngenta's product-fit dataset.
"""

import os
from google import genai
from dotenv import load_dotenv

load_dotenv()


def get_gemini_client(api_key: str = None):
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "No Gemini API key found. Set GEMINI_API_KEY in your .env file "
            "or pass api_key explicitly."
        )
    return genai.Client(api_key=key)


def build_prompt(field_report: dict, language: str = "Hindi"):
    readiness = field_report["readiness"]
    warning = field_report["early_warning"]

    prompt = f"""You are an agricultural advisory assistant writing a short SMS-style
message for an Indian smallholder farmer. Translate and phrase your
entire response in {language}, using simple words a farmer with no
technical background would understand. No jargon. Maximum 3 short
sentences. Do not invent specific product names — speak only about
general conditions and timing.

Data:
- Biological application readiness score: {readiness['score']} out of 100
  (higher = better conditions for applying a biological/biostimulant product)
- Confidence in this score: {readiness['confidence']}%
- Climate stress warning level: {warning['level']}
- Reason for warning: {warning['reason']}
- Rain risk flag (would wash away application): {readiness['rain_risk_flag']}

Write the farmer message now, in {language} only, no English, no preamble."""

    return prompt


def generate_advisory(field_report: dict, language: str = "Hindi", api_key: str = None):
    """
    Returns a dict with the generated message and metadata.
    Falls back to a safe, honest, English rule-based message if the
    Gemini call fails for any reason (never leave the farmer with
    nothing — reliability matters more than polish here).
    """
    try:
        client = get_gemini_client(api_key)
        prompt = build_prompt(field_report, language)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        message = response.text.strip()
        source = f"gemini ({model_name})"
    except Exception as e:
        message = _fallback_message(field_report)
        source = f"fallback_rule_based (gemini_error: {e})"

    return {
        "message": message,
        "language": language,
        "source": source,
    }


def _fallback_message(field_report: dict):
    """
    Simple deterministic English fallback if the Gemini API is
    unavailable — ensures the pipeline never silently fails to
    produce SOME actionable message.
    """
    readiness = field_report["readiness"]
    warning = field_report["early_warning"]

    score = readiness.get("score")
    level = warning.get("level")

    if level in ("CRITICAL", "HIGH"):
        return (f"Warning: {warning.get('reason', 'Stress conditions expected.')} "
                f"Consider applying biological treatment soon if conditions "
                f"otherwise look favorable (current readiness: {score}/100).")
    elif score is not None and score >= 70:
        return f"Conditions look favorable for biological application (readiness score: {score}/100)."
    elif score is not None:
        return f"Conditions are currently not ideal for application (readiness score: {score}/100). Consider waiting."
    else:
        return "Insufficient data to generate a recommendation right now. Please check again later."


if __name__ == "__main__":
    # Example using the real field report structure from readiness_engine.py
    example_report = {
        "readiness": {
            "score": 100.0,
            "confidence": 100.0,
            "rain_risk_flag": False,
        },
        "early_warning": {
            "level": "HIGH",
            "reason": "Sustained heavy rainfall expected (48.2mm total) — waterlogging risk over coming days.",
        },
    }

    result = generate_advisory(example_report, language="Hindi")
    print(result)
