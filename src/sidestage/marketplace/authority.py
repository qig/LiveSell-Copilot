"""Server-established seller authority; never accepted from action payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from sidestage.domain.models import SellerId


NonEmpty = Annotated[str, StringConstraints(strict=True, min_length=1)]


class SellerAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seller_id: SellerId
    show_id: NonEmpty
    actor_id: NonEmpty
    actor_type: Literal["seller"] = "seller"
