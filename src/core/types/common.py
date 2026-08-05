"""Shared, framework-agnostic type aliases used across VAOS layers."""

from collections.abc import Mapping
from typing import Any, TypeVar

#: A JSON-serializable mapping, commonly used for plugin payloads and
#: freeform metadata that does not warrant its own value object.
JSONMapping = Mapping[str, Any]

#: Generic type variable representing a domain entity in generic Ports
#: such as repositories.
EntityT = TypeVar("EntityT")

#: Generic type variable representing a use case's input DTO.
InputT = TypeVar("InputT")

#: Generic type variable representing a use case's output DTO.
OutputT = TypeVar("OutputT")
