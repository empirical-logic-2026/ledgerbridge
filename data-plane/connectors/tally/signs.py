"""Confirms how Tally signs debit and credit amounts in its XML (schema.md Section 7).

Every ledger posting carries ISDEEMEDPOSITIVE (Yes = debit) and a signed AMOUNT. If debits
are always negative and credits always positive, canonical amount = -(Tally amount).
Results are counts only: no amounts or names are reported.
"""

import re
import xml.etree.ElementTree as ET  # noqa: N817
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")

_INVENTORY_LISTS = ("ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST")


def tally_amount(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = _NUMBER.match(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def _first_present(voucher: ET.Element, tags: Iterable[str]) -> list[ET.Element]:
    for tag in tags:
        found = voucher.findall(tag)
        if found:
            return found
    return []


def postings(voucher: ET.Element) -> list[ET.Element]:
    """The complete set of ledger postings of a voucher (schema.md Section 7).

    - ALLLEDGERENTRIES.LIST, when present, is complete. In TallyPrime item invoices it
      already includes the sales/purchase ledger posted through inventory, so inventory
      ACCOUNTINGALLOCATIONS must not be added again.
    - Otherwise LEDGERENTRIES.LIST holds only the non-inventory lines, and the inventory
      ACCOUNTINGALLOCATIONS supply the rest.
    - Entries without a ledger are skipped (cancelled vouchers keep an empty placeholder).
    """
    entries = voucher.findall("ALLLEDGERENTRIES.LIST")
    if not entries:
        entries = voucher.findall("LEDGERENTRIES.LIST")
        for inventory in _first_present(voucher, _INVENTORY_LISTS):
            entries.extend(inventory.findall("ACCOUNTINGALLOCATIONS.LIST"))
    return [e for e in entries if (e.findtext("LEDGERNAME") or "").strip()]


@dataclass
class SignCounts:
    negative: int = 0
    positive: int = 0
    zero: int = 0

    def add(self, amount: Decimal) -> None:
        if amount < 0:
            self.negative += 1
        elif amount > 0:
            self.positive += 1
        else:
            self.zero += 1


@dataclass
class SignReport:
    vouchers: int = 0
    postings: int = 0
    unparsable: int = 0
    debit: SignCounts = field(default_factory=SignCounts)
    credit: SignCounts = field(default_factory=SignCounts)
    balanced_vouchers: int = 0
    unbalanced_vouchers: int = 0
    anchor: str | None = None

    @property
    def debits_negative(self) -> bool:
        """True when the data confirms: debit negative, credit positive."""
        return (
            self.postings > 0
            and self.debit.positive == 0
            and self.credit.negative == 0
            and self.unbalanced_vouchers == 0
        )

    def lines(self) -> list[str]:
        verdict = (
            "CONFIRMED: Tally debits are negative, credits positive; "
            "canonical amount = -(Tally amount)"
            if self.debits_negative
            else "NOT CONFIRMED: see counts above"
        )
        out = [
            f"vouchers checked: {self.vouchers}",
            f"ledger postings: {self.postings} (unparsable amounts: {self.unparsable})",
            f"debit postings  (ISDEEMEDPOSITIVE=Yes): negative {self.debit.negative}, "
            f"positive {self.debit.positive}, zero {self.debit.zero}",
            f"credit postings (ISDEEMEDPOSITIVE=No):  negative {self.credit.negative}, "
            f"positive {self.credit.positive}, zero {self.credit.zero}",
            f"vouchers summing to zero: {self.balanced_vouchers}, "
            f"not summing to zero: {self.unbalanced_vouchers}",
        ]
        if self.anchor:
            out.append(f"anchor voucher: {self.anchor}")
        out.append(verdict)
        return out


def check_vouchers(
    vouchers: Iterable[ET.Element],
    anchor_voucher: str | None = None,
    anchor_ledger: str | None = None,
) -> SignReport:
    report = SignReport()
    for voucher in vouchers:
        report.vouchers += 1
        total = Decimal(0)
        # The anchor is identified by its voucher number or by text in its narration.
        is_anchor = anchor_voucher is not None and (
            (voucher.findtext("VOUCHERNUMBER") or "").strip() == anchor_voucher
            or anchor_voucher in (voucher.findtext("NARRATION") or "")
        )
        for entry in postings(voucher):
            amount = tally_amount(entry.findtext("AMOUNT"))
            if amount is None:
                report.unparsable += 1
                continue
            report.postings += 1
            total += amount
            is_debit = (entry.findtext("ISDEEMEDPOSITIVE") or "").strip().lower() == "yes"
            (report.debit if is_debit else report.credit).add(amount)
            ledger = (entry.findtext("LEDGERNAME") or "").strip()
            if is_anchor and ledger == anchor_ledger:
                sign = "negative" if amount < 0 else "positive" if amount > 0 else "zero"
                side = "debit" if is_debit else "credit"
                report.anchor = f"line for the given ledger is a {side} and its AMOUNT is {sign}"
        if total == 0:
            report.balanced_vouchers += 1
        else:
            report.unbalanced_vouchers += 1
    if anchor_voucher is not None and report.anchor is None:
        report.anchor = "not found (check voucher number and ledger name)"
    return report


@dataclass
class OpeningReport:
    ledgers: int = 0
    signs: SignCounts = field(default_factory=SignCounts)
    sums_to_zero: bool = False
    anchor: str | None = None

    def lines(self) -> list[str]:
        out = [
            f"ledgers checked: {self.ledgers}",
            f"opening balances: negative {self.signs.negative}, positive {self.signs.positive}, "
            f"zero {self.signs.zero}",
            f"opening balances sum to zero: {'yes' if self.sums_to_zero else 'no'}",
        ]
        if self.anchor:
            out.append(
                f"anchor ledger (known debit opening balance): OPENINGBALANCE is {self.anchor}"
            )
        return out


def check_opening_balances(
    ledgers: Iterable[ET.Element], anchor_ledger: str | None = None
) -> OpeningReport:
    """Opening balances: their signs, whether they sum to zero, and one known-debit anchor."""
    report = OpeningReport()
    total = Decimal(0)
    for ledger in ledgers:
        amount = tally_amount(ledger.findtext("OPENINGBALANCE")) or Decimal(0)
        report.ledgers += 1
        report.signs.add(amount)
        total += amount
        name = (ledger.findtext("NAME") or ledger.get("NAME") or "").strip()
        if anchor_ledger is not None and name == anchor_ledger:
            report.anchor = "negative" if amount < 0 else "positive" if amount > 0 else "zero"
    report.sums_to_zero = total == 0
    if anchor_ledger is not None and report.anchor is None:
        report.anchor = "not found (check ledger name)"
    return report


@dataclass
class SideReport:
    """Tally's own Dr/Cr judgement ($$IsDr) compared with the sign of the XML amount."""

    agree: int = 0
    disagree: int = 0
    zero: int = 0
    anchors: dict[str, str] = field(default_factory=dict)

    @property
    def debits_negative(self) -> bool:
        return self.agree > 0 and self.disagree == 0

    def lines(self) -> list[str]:
        out = [
            f"non-zero opening/closing balances where Tally's $$IsDr agrees that "
            f"debit = negative: {self.agree}, disagrees: {self.disagree} (zero: {self.zero})"
        ]
        out += [f"anchor {name}: {text}" for name, text in self.anchors.items()]
        out.append(
            "CONFIRMED by Tally's own $$IsDr: debit balances are negative in XML"
            if self.debits_negative
            else "NOT CONFIRMED: see counts above"
        )
        return out


def check_balance_sides(ledgers: Iterable[ET.Element], anchors: Iterable[str] = ()) -> SideReport:
    """For each ledger balance, does Tally's $$IsDr (Yes = debit) match a negative amount?

    Anchor ledgers are reported with their closing balance and side as Tally's Trial
    Balance shows it, for comparison with TallyPrime. Use only on the test company.
    """
    report = SideReport()
    wanted = set(anchors)
    for ledger in ledgers:
        name = (ledger.findtext("NAME") or ledger.get("NAME") or "").strip()
        for field_name, flag in (
            ("OPENINGBALANCE", "LBOPENINGISDR"),
            ("CLOSINGBALANCE", "LBCLOSINGISDR"),
        ):
            amount = tally_amount(ledger.findtext(field_name)) or Decimal(0)
            is_dr = (ledger.findtext(flag) or "").strip().lower() == "yes"
            if amount == 0:
                report.zero += 1
            elif (amount < 0) == is_dr:
                report.agree += 1
            else:
                report.disagree += 1
            if name in wanted and field_name == "CLOSINGBALANCE":
                side = "Dr" if is_dr else "Cr"
                sign = "negative" if amount < 0 else "positive" if amount > 0 else "zero"
                report.anchors[name] = f"closing {abs(amount):,.2f} {side} (XML amount {sign})"
    for name in wanted - report.anchors.keys():
        report.anchors[name] = "not found"
    return report
