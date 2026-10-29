"""Tests for data_cleaning/margins.py: reliability labels from 90% margins."""

import duckdb
import pytest

from data_cleaning.margins import reliability_sql


@pytest.mark.parametrize(
    ("estimate", "moe", "label"),
    [
        (100, 24, "high"),  # CV 14.6%
        (100, 25, "medium"),  # CV 15.2%
        (100, 49, "medium"),  # CV 29.8%
        (100, 50, "low"),  # CV 30.4%
        (40, 0, "high"),  # controlled: no sampling error
        (0, 12, "low"),  # CV undefined; the true value may not be zero
        (None, 12, None),
        (100, None, None),
    ],
)
def test_reliability_follows_the_coefficient_of_variation(estimate, moe, label):
    sql = f"SELECT {reliability_sql('e', 'm')} FROM (SELECT ?::DOUBLE e, ?::DOUBLE m)"
    assert duckdb.execute(sql, [estimate, moe]).fetchone() == (label,)
