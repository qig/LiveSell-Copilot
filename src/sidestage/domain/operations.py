"""Marketplace operation vocabulary and authority ownership."""

from enum import Enum
from typing import FrozenSet


class OperationType(str, Enum):
    """The exact five authenticated seller operation types."""

    PUSH = "push"
    SWAP = "swap"
    UNLIST = "unlist"
    PRICE_MARKDOWN = "price_markdown"
    INVENTORY_CHANGE = "inventory_change"


SELLER_OPERATION_TYPES: FrozenSet[OperationType] = frozenset(OperationType)
