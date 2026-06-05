"""Unit tests for DataNormalizer.repositories.scoring_repo."""
from __future__ import annotations

import uuid

import pytest

from DataNormalizer.repositories import scoring_repo


@pytest.mark.asyncio
async def test_create_scores_happy_path_scales_score_x100(mock_conn):
    score_uuid = uuid.uuid4()
    mock_conn.fetchrow.return_value = {"score_id": score_uuid}
    offering_id = str(uuid.uuid4())

    result = await scoring_repo.create_scores(str(uuid.uuid4()), [
        {
            "offering_id":     offering_id,
            "rank":            1,
            "composite_score": 0.85,
            "price_value":     "150.00",
        },
    ])

    assert result == [{"offering_id": offering_id, "score_id": str(score_uuid)}]
    args = mock_conn.fetchrow.await_args.args
    # args: sql, offering_uuid, rank, total_score, tco, explanation, model_version
    assert args[3] == 85.0     # 0.85 × 100
    assert args[4] == 150.0    # tco from price_value
    assert args[5] == "Automated scoring"  # default explanation
    assert args[6] == "1.0"               # default model_version


@pytest.mark.asyncio
async def test_create_scores_clamps_above_one_to_100(mock_conn, caplog):
    mock_conn.fetchrow.return_value = {"score_id": uuid.uuid4()}

    with caplog.at_level("WARNING"):
        await scoring_repo.create_scores(str(uuid.uuid4()), [{
            "offering_id":     str(uuid.uuid4()),
            "composite_score": 1.5,
        }])

    args = mock_conn.fetchrow.await_args.args
    assert args[3] == 100.0
    assert any("clamped" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_create_scores_skips_entries_without_offering_id(mock_conn):
    mock_conn.fetchrow.return_value = {"score_id": uuid.uuid4()}

    result = await scoring_repo.create_scores(str(uuid.uuid4()), [
        {"rank": 1, "composite_score": 0.5},   # no offering_id
        {"offering_id": str(uuid.uuid4()), "rank": 2, "composite_score": 0.4},
    ])

    assert len(result) == 1
    assert mock_conn.fetchrow.await_count == 1


@pytest.mark.asyncio
async def test_create_scores_non_numeric_tco_defaults_to_zero(mock_conn, caplog):
    mock_conn.fetchrow.return_value = {"score_id": uuid.uuid4()}

    with caplog.at_level("WARNING"):
        await scoring_repo.create_scores(str(uuid.uuid4()), [{
            "offering_id": str(uuid.uuid4()),
            "rank":        1,
            "composite_score": 0.5,
            "price_value": "not-a-number",
        }])

    args = mock_conn.fetchrow.await_args.args
    assert args[4] == 0.0
    assert any("non-numeric tco" in r.message for r in caplog.records)
