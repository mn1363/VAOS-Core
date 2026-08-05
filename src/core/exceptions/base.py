"""Root exception type for all VAOS-specific errors."""


class VAOSError(Exception):
    """Base class for every exception explicitly raised by VAOS.

    Catching `VAOSError` allows callers to distinguish failures that are
    part of the documented VAOS contract from unexpected third-party or
    runtime errors.
    """

    def __init__(self, message: str) -> None:
        """Initialize the error with a human-readable message.

        Args:
            message: Description of what went wrong.
        """
        super().__init__(message)
        self.message = message
