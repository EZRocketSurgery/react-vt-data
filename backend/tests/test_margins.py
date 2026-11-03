"""Tests for data_cleaning/margins.py: reliability labels and combined 90% margins."""

import math

import duckdb
import pytest

from data_cleaning.margins import ratio_moe_sql, reliability_sql, sum_moe_sql


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


def summed_margin(*terms):
    pairs = [(f"e{i}", f"m{i}") for i in range(len(terms))]
    cols = ", ".join(f"?::DOUBLE {e}, ?::DOUBLE {m}" for e, m in pairs)
    sql = f"SELECT {sum_moe_sql(pairs)} FROM (SELECT {cols})"
    return duckdb.execute(sql, [x for t in terms for x in t]).fetchone()[0]


def test_summed_margin_is_the_root_sum_of_squares():
    assert summed_margin((100, 30), (50, 40)) == pytest.approx(50.0)


def test_summed_margin_counts_only_the_largest_zero_estimate_margin():
    expected = math.sqrt(30**2 + 25**2)
    assert summed_margin((100, 30), (0, 20), (0, 25)) == pytest.approx(expected)


def test_summed_margin_of_only_zero_estimates_is_their_largest():
    assert summed_margin((0, 20), (0, 25)) == pytest.approx(25.0)


def test_summed_margin_is_null_when_any_margin_is():
    assert summed_margin((100, 30), (0, None)) is None


def test_ratio_margin():
    sql = f"SELECT {ratio_moe_sql('0.5', '40', '1000', '60')}"
    # sqrt(40^2 + 0.5^2 * 60^2) / 1000
    assert duckdb.execute(sql).fetchone()[0] == pytest.approx(0.05)
