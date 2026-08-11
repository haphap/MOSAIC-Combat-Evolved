class DataVendorUnavailable(Exception):
    """Raised when a vendor cannot serve a request and fallback should be attempted."""

    def __init__(
        self,
        message: str = "",
        *,
        reason_code: str = "DATA_VENDOR_UNAVAILABLE",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class MissingEtfHoldings(DataVendorUnavailable):
    """Raised when an ETF has no disclosed equity holdings for the requested date."""
