"""Plain-language explanations for every signal and portfolio allocation."""
from .reasoning import (
    explain_allocation,
    explain_no_signal,
    explain_signal,
    explain_stance,
)

__all__ = [
    "explain_signal", "explain_allocation", "explain_no_signal", "explain_stance",
]
