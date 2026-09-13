"""One-time offline job: embed the bullish/bearish reference phrases and
write their centroid vectors to backend/sentiment_anchors.json.

Why this is a separate offline script instead of code that runs at request
time or at server startup: these phrases never change at runtime, so
re-embedding them on every boot would just be a slower, more expensive way
to get the same 1536-dimension vectors every time. Compute them once,
commit the resulting JSON, and the sentiment engine (sentiment_engine.py)
never has to make an OpenAI call at all -- it only does cosine similarity
against numbers that are already in the file.

Run it once whenever you change the phrase lists below:

    cd backend
    python scripts/generate_sentiment_anchors.py

Requires OPENAI_API_KEY to be set (reads it the same way the rest of the
backend does, via backend/.env). Cost is a fraction of a cent -- ~30 short
phrases through text-embedding-3-small.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vector_pipeline import embed_text  # noqa: E402

EMBEDDING_MODEL = "text-embedding-3-small"

# Keep these short, concrete, and finance-specific -- the anchor should read
# like a headline, not a general-purpose sentiment word list, since it's
# being compared against embeddings of actual news headlines/summaries.
BULLISH_PHRASES = [
    "Company beats earnings expectations and raises full-year guidance.",
    "Stock surges after posting record quarterly revenue.",
    "Company wins a major new government contract.",
    "Analysts upgrade the stock and raise their price target.",
    "Company announces a larger-than-expected share buyback program.",
    "Regulators approve the company's new product for sale.",
    "Company reports strong subscriber and user growth.",
    "Institutional investors are accumulating shares amid rising demand.",
    "Company secures a strategic partnership with an industry leader.",
    "Sales guidance was raised well above Wall Street estimates.",
]

BEARISH_PHRASES = [
    "Company misses earnings estimates and issues a profit warning.",
    "Stock plunges after weaker-than-expected quarterly results.",
    "Company faces a regulatory investigation into its business practices.",
    "Analysts downgrade the stock and cut their price target.",
    "Company announces layoffs amid slowing demand.",
    "Regulators reject the company's application over safety concerns.",
    "Company reports declining subscriber and user growth.",
    "Institutional investors are selling off shares amid weak outlook.",
    "Company loses a major contract to a competitor.",
    "Guidance was cut well below Wall Street estimates.",
]


def _centroid(vectors: list[list[float]]) -> list[float]:
    dimension = len(vectors[0])
    totals = [0.0] * dimension
    for vector in vectors:
        for index, value in enumerate(vector):
            totals[index] += value
    return [value / len(vectors) for value in totals]


def main() -> None:
    print(f"Embedding {len(BULLISH_PHRASES)} bullish and {len(BEARISH_PHRASES)} bearish anchor phrases...")
    bullish_vectors = [embed_text(phrase) for phrase in BULLISH_PHRASES]
    bearish_vectors = [embed_text(phrase) for phrase in BEARISH_PHRASES]

    payload = {
        "model": EMBEDDING_MODEL,
        "bullish_phrases": BULLISH_PHRASES,
        "bearish_phrases": BEARISH_PHRASES,
        "bullish_centroid": _centroid(bullish_vectors),
        "bearish_centroid": _centroid(bearish_vectors),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = Path(__file__).resolve().parent.parent / "sentiment_anchors.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
