# Import functions from specialized modules
from .alpha_vantage_stock import get_stock
from .alpha_vantage_indicator import get_indicator
from .alpha_vantage_fundamentals import get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement
from .alpha_vantage_news import get_news, get_global_news, get_insider_transactions

# This module is a re-export facade: it is the public entrypoint for the
# Alpha Vantage vendor functions implemented in the specialised submodules.
__all__ = [
    "get_stock",
    "get_indicator",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_global_news",
    "get_insider_transactions",
]