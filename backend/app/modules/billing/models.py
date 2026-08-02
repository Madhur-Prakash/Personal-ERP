"""Payment cards - identifying which card money moved on.

**The full card number is never stored, and this module is written so that it cannot
be.** A Primary Account Number is the one field that brings an entire database into PCI
DSS scope, and this is self-hosted software with no key management, no tokenisation
service, and no obligation to have either. What a shopkeeper actually needs is to tell
*which* card a payment went on, and the last four digits plus the network do that
completely - it is what the card itself prints on a receipt, and what every bank
statement shows.

So the API accepts a number, validates it, derives :attr:`PaymentCard.network` and
:attr:`PaymentCard.last4`, and throws the rest away before anything is written or
logged. There is no column that could hold a PAN, which is a stronger guarantee than a
rule saying not to put one there.

**A credit card is a liability, not cash - and that distinction is the whole reason
this module exists rather than reusing "add a bank account".** Paying by credit card
does not move money; it creates a debt to the issuer. Modelling it as a cash-equivalent
asset would put a card balance inside the dashboard's "Cash and bank" figure and inside
the cash flow statement's definition of cash, and both would then be wrong in a way that
looks plausible. So a credit card gets its own liability account under Current
Liabilities, and paying it off from a bank account is an ordinary transfer.

**A debit card is not an account at all**, and pretending otherwise would double-count
the money. The card is a way of touching a bank account that already exists, so adding
one attaches a label and last four digits *to that account* rather than creating a
second one. The picker can then offer "HDFC Bank ··4242" while every posting still lands
on the single real account.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_column

if TYPE_CHECKING:
    from app.modules.accounting.models import Account
    from app.modules.organizations.models import Organization


class CardKind(StrEnum):
    """What kind of card, which decides where its postings land.

    Not cosmetic. The two are different accounting objects, and the difference is the
    reason this enum exists rather than a single "card" concept.
    """

    #: Spending creates a debt to the issuer. Gets its own liability account.
    CREDIT = "credit"
    #: Spending moves money out of a bank account that already exists. Gets no account
    #: of its own - it is a label on that one.
    DEBIT = "debit"

    @property
    def label(self) -> str:
        return "Credit card" if self is CardKind.CREDIT else "Debit card"

    @property
    def has_own_account(self) -> bool:
        return self is CardKind.CREDIT


class CardNetwork(StrEnum):
    """The scheme the number belongs to, derived from its leading digits.

    Stored rather than re-derived because the number it was derived from is deliberately
    gone. Kept as a closed set so the UI can show a recognisable name; anything the
    prefix table does not recognise is :attr:`OTHER`, which is honest and harmless -
    the card still works, the software just does not claim to know the scheme.
    """

    VISA = "visa"
    MASTERCARD = "mastercard"
    RUPAY = "rupay"
    AMEX = "amex"
    DISCOVER = "discover"
    DINERS = "diners"
    JCB = "jcb"
    MAESTRO = "maestro"
    OTHER = "other"

    @property
    def label(self) -> str:
        return _NETWORK_LABELS[self]


_NETWORK_LABELS: Final[dict[CardNetwork, str]] = {
    CardNetwork.VISA: "Visa",
    CardNetwork.MASTERCARD: "Mastercard",
    CardNetwork.RUPAY: "RuPay",
    CardNetwork.AMEX: "American Express",
    CardNetwork.DISCOVER: "Discover",
    CardNetwork.DINERS: "Diners Club",
    CardNetwork.JCB: "JCB",
    CardNetwork.MAESTRO: "Maestro",
    CardNetwork.OTHER: "Card",
}


class PaymentCard(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """A card money moves on, identified by its last four digits.

    **There is no column for a card number**, and that absence is the design. See the
    module docstring.
    """

    #: What the user calls it - "Business Amex", "HDFC debit". Free text, because the
    #: scheme and the last four are not enough to tell two HDFC cards apart.
    label: Mapped[str] = mapped_column(String(80), nullable=False)

    kind: Mapped[CardKind] = mapped_column(enum_column(CardKind, length=10), nullable=False)

    network: Mapped[CardNetwork] = mapped_column(
        enum_column(CardNetwork, length=12), nullable=False
    )

    #: Exactly four digits, as a string. A string rather than an integer because a card
    #: ending 0042 is not the number 42, and the leading zeros are the point.
    last4: Mapped[str] = mapped_column(String(4), nullable=False)

    #: The ledger account this card's postings land on.
    #:
    #: A credit card owns its account, which was created alongside it. A debit card
    #: points at a bank account that already existed and is shared with every other way
    #: of touching that account. ``RESTRICT`` rather than ``CASCADE``: an account with
    #: postings against it is not deletable anyway, and silently removing a card because
    #: something happened to an account would lose the record of which card was used.
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    #: Archived rather than deleted, for the same reason a product is: entries already
    #: reference the account, and the card is how someone recognises them.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped[Organization] = relationship(lazy="raise")
    account: Mapped[Account] = relationship(lazy="raise")

    __table_args__ = (
        # The same scheme and last four twice in one organization is almost always a
        # double-entry rather than two genuinely different cards. Scoped by kind as
        # well, because a bank issuing a debit and a credit card on the same account
        # range can legitimately produce a collision.
        UniqueConstraint(
            "organization_id",
            "network",
            "last4",
            "kind",
            name="uq_payment_card_org_network_last4_kind",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PaymentCard {self.label} {self.network.value} ··{self.last4}>"

    @property
    def display_name(self) -> str:
        """What the picker shows: "Business Amex ··4242"."""
        return f"{self.label} ··{self.last4}"
