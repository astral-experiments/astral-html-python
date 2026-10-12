"""Conservative formatting for benchmark means and their standard errors."""

from decimal import ROUND_HALF_UP, Decimal


def format_measurement(mean: float, standard_error: float) -> str:
    """Show at most three significant digits for the mean and one for the SE.

    The mean is never shown more finely than the SE. The SE is shown separately
    because it may be smaller than the mean's displayed resolution. An SE of
    zero can arise from limited measurement resolution; it does not imply exactness.
    """
    value = Decimal(str(mean))
    error = Decimal(str(standard_error))

    if error:
        error_place = error.adjusted()
        rounded_error = error.quantize(Decimal(1).scaleb(error_place), ROUND_HALF_UP)
        # Rounding 9.9 to 10 shifts the place of its single significant digit.
        error_place = rounded_error.adjusted()
    else:
        rounded_error = error
        error_place = None

    mean_place = value.adjusted() - 2 if value else 0
    if error_place is not None:
        mean_place = max(mean_place, error_place)
    rounded_mean = value.quantize(Decimal(1).scaleb(mean_place), ROUND_HALF_UP)
    # Rounding can carry the mean into the next decade, e.g. 9.999 to 10.00.
    # Recalculate the place so that the result still has at most three digits.
    if rounded_mean and rounded_mean.adjusted() - 2 > mean_place:
        mean_place = rounded_mean.adjusted() - 2
        rounded_mean = value.quantize(Decimal(1).scaleb(mean_place), ROUND_HALF_UP)

    mean_text = f"{rounded_mean:,.{max(0, -mean_place)}f}"
    if error_place is None:
        error_text = "0"
    else:
        error_text = f"{rounded_error:,.{max(0, -error_place)}f}"
    return f"{mean_text} (SE {error_text})"
