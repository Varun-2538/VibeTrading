from typing import Optional


def format_price(price: float, decimals: int = 2) -> str:
    """
    Format price with proper decimal places

    Args:
        price: Price value
        decimals: Number of decimal places

    Returns:
        Formatted price string
    """
    return f"${price:,.{decimals}f}"


def calculate_percentage_change(
    current: float,
    previous: float
) -> float:
    """
    Calculate percentage change between two values

    Args:
        current: Current value
        previous: Previous value

    Returns:
        Percentage change
    """
    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safe division with default value for division by zero

    Args:
        numerator: Numerator
        denominator: Denominator
        default: Default value if denominator is zero

    Returns:
        Division result or default
    """
    return numerator / denominator if denominator != 0 else default


def round_to_tick(price: float, tick_size: float = 0.01) -> float:
    """
    Round price to nearest tick size

    Args:
        price: Price to round
        tick_size: Tick size (e.g., 0.01 for 2 decimals)

    Returns:
        Rounded price
    """
    return round(price / tick_size) * tick_size
