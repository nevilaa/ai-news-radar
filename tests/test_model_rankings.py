import json
from datetime import datetime, timezone

import pytest

from scripts.update_model_rankings import build_payload, extract_initial_models


def sample_html(count: int = 12) -> str:
    models = []
    for index in range(count):
        models.append(
            {
                "name": f"Model {index}",
                "shortName": f"M{index}",
                "slug": f"model-{index}",
                "releaseDate": "2026-01-01",
                "isReasoning": index % 2 == 0,
                "isOpenWeights": index % 3 == 0,
                "intelligenceIndex": 40 + index,
                "intelligenceIndexIsEstimated": False,
                "agenticIndex": 30 + (count - index),
                "agenticIndexIsEstimated": index == 0,
            }
        )
    flight = '0:{"initialModels":' + json.dumps(models, separators=(",", ":")) + "}"
    escaped = json.dumps(flight)
    return (
        '<html><body>Artificial Analysis Intelligence Index v4.1.1'
        f'<script>self.__next_f.push([1,{escaped}])</script></body></html>'
    )


def test_extract_initial_models_from_next_flight_chunk():
    models = extract_initial_models(sample_html())
    assert len(models) == 12
    assert models[0]["slug"] == "model-0"


def test_build_payload_sorts_each_index_independently():
    fetched_at = datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc)
    payload = build_payload(sample_html(), fetched_at, limit=5)

    intelligence = payload["indexes"]["intelligence"]
    agentic = payload["indexes"]["agentic"]
    assert intelligence["version"] == "4.1.1"
    assert intelligence["models"][0]["name"] == "Model 11"
    assert intelligence["models"][0]["rank"] == 1
    assert agentic["models"][0]["name"] == "Model 0"
    assert agentic["models"][0]["is_estimated"] is True
    assert payload["fetched_at"] == "2026-08-22T01:02:03Z"


def test_extract_initial_models_rejects_missing_dataset():
    with pytest.raises(ValueError, match="initialModels"):
        extract_initial_models("<html></html>")
