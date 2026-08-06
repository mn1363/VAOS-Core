"""Unit tests for `src.core.exceptions`."""

import pytest
from src.core.exceptions import (
    ConfigurationError,
    NotFoundError,
    ValidationError,
    VAOSError,
)


def test_vaos_error_str_returns_message() -> None:
    """`str(VAOSError(...))` should return the plain message."""
    error = VAOSError("something went wrong")

    assert str(error) == "something went wrong"
    assert error.message == "something went wrong"
    assert error.details == {}


def test_vaos_error_carries_structured_details() -> None:
    """Structured `details` should be stored without affecting `str()`."""
    error = VAOSError("bad value", details={"field": "environment", "value": "prod"})

    assert error.details == {"field": "environment", "value": "prod"}
    assert str(error) == "bad value"


@pytest.mark.parametrize("exc_type", [ConfigurationError, ValidationError, NotFoundError])
def test_every_category_is_a_vaos_error(exc_type: type[VAOSError]) -> None:
    """Every specific exception category should still be catchable as `VAOSError`."""
    error = exc_type("failure")

    assert isinstance(error, VAOSError)
    assert isinstance(error, Exception)


def test_categories_are_not_interchangeable() -> None:
    """Distinct categories should not satisfy each other's isinstance checks."""
    assert not isinstance(ConfigurationError("x"), ValidationError)
    assert not isinstance(NotFoundError("x"), ConfigurationError)
    assert not isinstance(ValidationError("x"), NotFoundError)
