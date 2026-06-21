"""Trading strategies and the Strategy/Signal contract.

Importing this package registers all bundled strategies so that
:func:`build_strategy` / :func:`all_strategy_names` can find them by name.
"""
from .base import (
    BUY,
    HOLD,
    SELL,
    Signal,
    Strategy,
    all_strategy_names,
    build_strategy,
    register,
)
from .factor_model import FactorModel
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy

__all__ = [
    "Strategy", "Signal", "BUY", "SELL", "HOLD",
    "register", "build_strategy", "all_strategy_names",
    "MomentumStrategy", "MeanReversionStrategy", "FactorModel",
]
