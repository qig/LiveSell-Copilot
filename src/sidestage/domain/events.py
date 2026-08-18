"""Customer-input contracts introduced by M2.1."""

from enum import Enum


class CustomerInputType(str, Enum):
    """The prototype customer has exactly one input surface."""

    CHAT_MESSAGE = "chat_message"
