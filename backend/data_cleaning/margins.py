"""
**Description**:
    Shared SQL for ACS margins of error in the cleaning step.

    Each margin of error column (`<measure>_moe`, or `moe` in the data
    profiles) gets a reliability label beside it, from the coefficient of
    variation CV = standard error / estimate, where the standard error of an
    ACS 90% margin is MOE / 1.645. The Census Bureau sets no fixed cut
    points; CV under 15% (high) and over 30% (low) is a common convention
    among ACS data users.
"""

Z_90 = 1.645
HIGH_CV = 0.15  # below this, high reliability
LOW_CV = 0.30  # above this, low reliability


def reliability_sql(estimate: str, moe: str) -> str:
    """
    'high', 'medium' or 'low' reliability for an estimate and its 90% margin.

    A zero estimate with a nonzero margin is 'low': its CV is undefined, and
    the true value may well not be zero. A zero margin (a controlled
    estimate) is 'high'. Null when either input is null.

    Args:
        estimate: SQL expression for the estimate
        moe: SQL expression for its margin of error

    Returns:
        str: A SQL CASE expression
    """
    cv = f"{moe} / {Z_90} / ABS({estimate})"
    return f"""CASE
        WHEN {estimate} IS NULL OR {moe} IS NULL THEN NULL
        WHEN {moe} = 0 THEN 'high'
        WHEN {estimate} = 0 THEN 'low'
        WHEN {cv} < {HIGH_CV} THEN 'high'
        WHEN {cv} <= {LOW_CV} THEN 'medium'
        ELSE 'low'
    END"""


def sum_moe_sql(terms: list[tuple[str, str]]) -> str:
    """
    90% margin of a sum of estimates: the root sum of their squared margins
    (ACS handbook). As in data_collection.base.sum_moe, only the largest
    margin among zero estimates counts, since summing many modeled zero
    margins overstates the error. Null when any margin is null.

    Args:
        terms: (estimate, margin of error) SQL expression pairs

    Returns:
        str: A SQL expression
    """
    nonzero = " + ".join(
        f"CASE WHEN {e} = 0 THEN 0 ELSE ({m}) ^ 2 END" for e, m in terms
    )
    zero = ", ".join(f"CASE WHEN {e} = 0 THEN ({m}) ^ 2 ELSE 0 END" for e, m in terms)
    missing = " OR ".join(f"{m} IS NULL" for _, m in terms)
    return f"""CASE
        WHEN {missing} THEN NULL
        ELSE SQRT({nonzero} + GREATEST({zero}))
    END"""


def ratio_moe_sql(ratio: str, num_moe: str, den: str, den_moe: str) -> str:
    """
    90% margin of the ratio num / den, where num is not a subset of den:
    sqrt(num_moe^2 + ratio^2 * den_moe^2) / den (ACS handbook). A subset
    takes the proportion form instead (data_collection.base.proportion_moe).

    Args:
        ratio: SQL expression for num / den
        num_moe: SQL expression for the numerator's margin of error
        den: SQL expression for the denominator
        den_moe: SQL expression for the denominator's margin of error

    Returns:
        str: A SQL expression
    """
    return f"SQRT(({num_moe}) ^ 2 + ({ratio}) ^ 2 * ({den_moe}) ^ 2) / ({den})"
