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
