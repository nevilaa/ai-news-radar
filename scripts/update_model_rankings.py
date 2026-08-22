#!/usr/bin/env python3
"""Sync the public Artificial Analysis model leaderboards into a small JSON file."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


SOURCE_URL = "https://artificialanalysis.ai/models"
AGENTIC_URL = "https://artificialanalysis.ai/models/capabilities/agentic/"
USER_AGENT = "AI-News-Radar/1.0 (+https://www.shresearch.cn/ai-radar/classic/)"
NEXT_CHUNK_RE = re.compile(
    r"self\.__next_f\.push\(\[1,(\"(?:\\.|[^\"\\])*\")\]\)</script>"
)


def extract_initial_models(html: str) -> list[dict[str, Any]]:
    """Extract the default chart model set from Next.js flight data."""

    decoder = json.JSONDecoder()
    candidates: list[list[dict[str, Any]]] = []

    for match in NEXT_CHUNK_RE.finditer(html):
        try:
            chunk = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        marker = '"initialModels":'
        start = chunk.find(marker)
        while start >= 0:
            value_start = start + len(marker)
            try:
                value, _ = decoder.raw_decode(chunk[value_start:])
            except json.JSONDecodeError:
                break
            if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
                candidates.append(value)
            start = chunk.find(marker, value_start + 1)

    if not candidates:
        raise ValueError("Artificial Analysis page did not expose initialModels")

    models = max(candidates, key=len)
    if len(models) < 10:
        raise ValueError(f"Artificial Analysis returned only {len(models)} models")
    return models


def _score(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_ranking(models: list[dict[str, Any]], field: str, limit: int) -> list[dict[str, Any]]:
    selected = []
    for row in models:
        score = _score(row, field)
        slug = str(row.get("slug") or "").strip()
        name = str(row.get("name") or row.get("shortName") or "").strip()
        if score is None or not slug or not name:
            continue
        selected.append((score, name.casefold(), row))

    selected.sort(key=lambda item: (-item[0], item[1]))
    ranking = []
    for rank, (score, _, row) in enumerate(selected[:limit], start=1):
        slug = str(row["slug"]).strip()
        creator = row.get("creator") if isinstance(row.get("creator"), dict) else {}
        creator_logo = str(creator.get("logo") or "").strip()
        ranking.append(
            {
                "rank": rank,
                "name": str(row.get("name") or row.get("shortName")).strip(),
                "short_name": str(row.get("shortName") or row.get("name")).strip(),
                "score": round(score, 2),
                "slug": slug,
                "url": f"https://artificialanalysis.ai/models/{slug}",
                "release_date": row.get("releaseDate"),
                "is_reasoning": bool(row.get("isReasoning")),
                "is_open_weights": bool(row.get("isOpenWeights")),
                "is_estimated": bool(row.get(f"{field}IsEstimated")),
                "provider": {
                    "name": str(creator.get("name") or "").strip(),
                    "slug": str(creator.get("slug") or "").strip(),
                    "color": str(creator.get("color") or "").strip(),
                    "logo_url": urljoin(SOURCE_URL, creator_logo) if creator_logo else None,
                },
            }
        )

    if len(ranking) < min(5, limit):
        raise ValueError(f"Artificial Analysis returned only {len(ranking)} usable {field} rows")
    return ranking


def catalog_count_for(html: str, selected_count: int | None = None) -> int | None:
    pairs = [(int(selected), int(total)) for selected, total in re.findall(r"(\d{1,3}) of (\d{2,4}) models", html)]
    if selected_count is None:
        return max((total for _, total in pairs), default=None)
    totals = [total for selected, total in pairs if selected == selected_count]
    return max(totals) if totals else None


def build_payload(html: str, fetched_at: datetime, limit: int = 29) -> dict[str, Any]:
    models = extract_initial_models(html)
    version_match = re.search(r"Artificial Analysis Intelligence Index v([0-9.]+)", html)
    version = version_match.group(1) if version_match else None
    timestamp = fetched_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    intelligence_models = build_ranking(models, "intelligenceIndex", limit)
    agentic_models = build_ranking(models, "agenticIndex", limit)
    intelligence_available = sum(_score(row, "intelligenceIndex") is not None for row in models)
    agentic_available = sum(_score(row, "agenticIndex") is not None for row in models)

    return {
        "schema_version": "1.1",
        "fetched_at": timestamp,
        "refresh_interval_minutes": 60,
        "source": {
            "name": "Artificial Analysis",
            "url": SOURCE_URL,
            "agentic_url": AGENTIC_URL,
            "attribution": "Ranking data from Artificial Analysis",
        },
        "indexes": {
            "intelligence": {
                "title": "Artificial Analysis Intelligence Index",
                "version": version,
                "description": "综合知识、推理、数学、编程与真实任务评测的模型能力指数",
                "selected_model_count": intelligence_available,
                "catalog_model_count": catalog_count_for(html),
                "models": intelligence_models,
            },
            "agentic": {
                "title": "Agentic Index",
                "version": None,
                "description": "衡量模型完成真实代理任务与多步骤工作的能力",
                "selected_model_count": agentic_available,
                "catalog_model_count": catalog_count_for(html, agentic_available),
                "models": agentic_models,
            },
        },
    }


def fetch_html(session: requests.Session | None = None) -> str:
    client = session or requests.Session()
    response = client.get(
        SOURCE_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/model-rankings.json")
    parser.add_argument("--limit", type=int, default=29)
    args = parser.parse_args()
    if not 5 <= args.limit <= 30:
        parser.error("--limit must be between 5 and 30")

    payload = build_payload(fetch_html(), datetime.now(timezone.utc), args.limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Synced {sum(len(item['models']) for item in payload['indexes'].values())} ranking rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
