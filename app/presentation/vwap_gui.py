"""Compatibility aliases for the former VWAP-only GUI."""

from app.presentation.a8_gui import (
    A8GuiInput as VwapGuiInput,
    request_a8_backtest_input as request_vwap_backtest_input,
    show_a8_completion as show_vwap_completion,
)

__all__ = ["VwapGuiInput", "request_vwap_backtest_input", "show_vwap_completion"]
