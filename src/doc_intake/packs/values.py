"""Value types shared by the packs: money and currency codes."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

# Decimal, never float: money must keep its exact digits (project invariant 5).
# Pydantic's default already rejects NaN and infinities for Decimal.
type Money = Annotated[Decimal, Field(ge=0)]
# A rounding adjustment goes either way, as printed on the golden receipts.
type SignedMoney = Decimal
type CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
