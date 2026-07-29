"""The default chart of accounts seeded into a new organization.

A blank chart is useless to a small business — nobody starting a bakery knows they
need an "Accumulated Depreciation" contra-asset. So a working chart is seeded and
the owner prunes it, which is far easier than building one from nothing.

The numbering is the conventional five-block scheme, which every accountant reads
without explanation:

===========  ==================
``1xxx``     Assets
``2xxx``     Liabilities
``3xxx``     Equity
``4xxx``     Income
``5xxx``     Expenses
===========  ==================

Content is India-oriented (GST input/output, TDS payable) because that is the
default locale — ``Organization.currency`` defaults to INR and the fiscal year
starts in April. The structure is locale-neutral, so an alternate template is a
matter of adding a second list, not changing any logic.

``system_key`` marks the single default account for a role. Later stages resolve
by that key — an invoice credits ``sales_revenue`` and debits
``accounts_receivable`` — so this template is the contract between the ledger and
every module that posts into it.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from app.modules.accounting.models import AccountSubtype as Sub
from app.modules.accounting.models import AccountType as Type


class SystemAccount:
    """Keys that later stages resolve accounts by.

    Kept as plain constants rather than an enum so a deployment can add its own
    keys without editing this module.
    """

    CASH: Final = "cash"
    BANK: Final = "bank"
    ACCOUNTS_RECEIVABLE: Final = "accounts_receivable"
    ACCOUNTS_PAYABLE: Final = "accounts_payable"
    #: Goods Received Not Invoiced. Holds the liability for stock that has arrived
    #: before the supplier's invoice, so both months close correctly.
    GOODS_RECEIVED_NOT_INVOICED: Final = "grni"
    INVENTORY: Final = "inventory"
    SALES_REVENUE: Final = "sales_revenue"
    COST_OF_GOODS_SOLD: Final = "cost_of_goods_sold"
    GST_INPUT: Final = "gst_input"
    GST_OUTPUT: Final = "gst_output"
    RETAINED_EARNINGS: Final = "retained_earnings"
    OWNER_CAPITAL: Final = "owner_capital"
    ROUNDING: Final = "rounding"


class AccountSpec(NamedTuple):
    """One line of the template.

    ``parent`` is a *code*, not an id — the seeder resolves codes to ids as it
    walks the list, so the template stays readable and reorderable.
    """

    code: str
    name: str
    account_type: Type
    subtype: Sub
    parent: str | None = None
    is_group: bool = False
    system_key: str | None = None
    reconcilable: bool = False


#: Parents must appear before their children — the seeder inserts in order.
DEFAULT_CHART: Final[tuple[AccountSpec, ...]] = (
    # =========================================================================
    # 1xxx — Assets
    # =========================================================================
    AccountSpec("1000", "Assets", Type.ASSET, Sub.OTHER_ASSET, is_group=True),
    AccountSpec("1100", "Current Assets", Type.ASSET, Sub.OTHER_CURRENT_ASSET, "1000", True),
    AccountSpec(
        "1110",
        "Cash on Hand",
        Type.ASSET,
        Sub.CASH,
        "1100",
        system_key=SystemAccount.CASH,
        reconcilable=True,
    ),
    AccountSpec("1120", "Bank Accounts", Type.ASSET, Sub.BANK, "1100", True),
    AccountSpec(
        "1121",
        "Primary Bank Account",
        Type.ASSET,
        Sub.BANK,
        "1120",
        system_key=SystemAccount.BANK,
        reconcilable=True,
    ),
    AccountSpec(
        "1130",
        "Accounts Receivable",
        Type.ASSET,
        Sub.ACCOUNTS_RECEIVABLE,
        "1100",
        system_key=SystemAccount.ACCOUNTS_RECEIVABLE,
    ),
    AccountSpec(
        "1140",
        "Inventory",
        Type.ASSET,
        Sub.INVENTORY,
        "1100",
        system_key=SystemAccount.INVENTORY,
    ),
    AccountSpec(
        "1150",
        "GST Input Tax Credit",
        Type.ASSET,
        Sub.OTHER_CURRENT_ASSET,
        "1100",
        system_key=SystemAccount.GST_INPUT,
    ),
    AccountSpec("1160", "Prepaid Expenses", Type.ASSET, Sub.OTHER_CURRENT_ASSET, "1100"),
    AccountSpec("1170", "Advances to Suppliers", Type.ASSET, Sub.OTHER_CURRENT_ASSET, "1100"),
    AccountSpec("1200", "Fixed Assets", Type.ASSET, Sub.FIXED_ASSET, "1000", True),
    AccountSpec("1210", "Furniture & Fixtures", Type.ASSET, Sub.FIXED_ASSET, "1200"),
    AccountSpec("1220", "Plant & Machinery", Type.ASSET, Sub.FIXED_ASSET, "1200"),
    AccountSpec("1230", "Computers & Equipment", Type.ASSET, Sub.FIXED_ASSET, "1200"),
    AccountSpec("1240", "Vehicles", Type.ASSET, Sub.FIXED_ASSET, "1200"),
    # A contra-asset: normally carries a credit balance despite being an asset,
    # which is exactly why depreciation is tracked separately from cost.
    AccountSpec(
        "1290", "Accumulated Depreciation", Type.ASSET, Sub.ACCUMULATED_DEPRECIATION, "1200"
    ),
    # =========================================================================
    # 2xxx — Liabilities
    # =========================================================================
    AccountSpec("2000", "Liabilities", Type.LIABILITY, Sub.OTHER_CURRENT_LIABILITY, is_group=True),
    AccountSpec(
        "2100", "Current Liabilities", Type.LIABILITY, Sub.OTHER_CURRENT_LIABILITY, "2000", True
    ),
    AccountSpec(
        "2110",
        "Accounts Payable",
        Type.LIABILITY,
        Sub.ACCOUNTS_PAYABLE,
        "2100",
        system_key=SystemAccount.ACCOUNTS_PAYABLE,
    ),
    AccountSpec(
        "2115",
        "Goods Received Not Invoiced",
        Type.LIABILITY,
        Sub.OTHER_CURRENT_LIABILITY,
        "2100",
        system_key=SystemAccount.GOODS_RECEIVED_NOT_INVOICED,
    ),
    AccountSpec(
        "2120",
        "GST Output Tax",
        Type.LIABILITY,
        Sub.TAX_PAYABLE,
        "2100",
        system_key=SystemAccount.GST_OUTPUT,
    ),
    AccountSpec("2130", "TDS Payable", Type.LIABILITY, Sub.TAX_PAYABLE, "2100"),
    AccountSpec("2140", "Salaries Payable", Type.LIABILITY, Sub.OTHER_CURRENT_LIABILITY, "2100"),
    AccountSpec(
        "2150", "Advances from Customers", Type.LIABILITY, Sub.OTHER_CURRENT_LIABILITY, "2100"
    ),
    AccountSpec(
        "2200", "Long-term Liabilities", Type.LIABILITY, Sub.LONG_TERM_LIABILITY, "2000", True
    ),
    AccountSpec("2210", "Bank Loans", Type.LIABILITY, Sub.LONG_TERM_LIABILITY, "2200"),
    # =========================================================================
    # 3xxx — Equity
    # =========================================================================
    AccountSpec("3000", "Equity", Type.EQUITY, Sub.CAPITAL, is_group=True),
    AccountSpec(
        "3100",
        "Owner's Capital",
        Type.EQUITY,
        Sub.CAPITAL,
        "3000",
        system_key=SystemAccount.OWNER_CAPITAL,
    ),
    # Drawings reduce equity, so it carries a debit balance within a
    # credit-normal type. Modelled as an ordinary equity account because that is
    # how it appears on the balance sheet.
    AccountSpec("3200", "Owner's Drawings", Type.EQUITY, Sub.DRAWINGS, "3000"),
    AccountSpec(
        "3300",
        "Retained Earnings",
        Type.EQUITY,
        Sub.RETAINED_EARNINGS,
        "3000",
        system_key=SystemAccount.RETAINED_EARNINGS,
    ),
    # =========================================================================
    # 4xxx — Income
    # =========================================================================
    AccountSpec("4000", "Income", Type.INCOME, Sub.OPERATING_REVENUE, is_group=True),
    AccountSpec(
        "4100",
        "Sales Revenue",
        Type.INCOME,
        Sub.OPERATING_REVENUE,
        "4000",
        system_key=SystemAccount.SALES_REVENUE,
    ),
    AccountSpec("4200", "Service Revenue", Type.INCOME, Sub.OPERATING_REVENUE, "4000"),
    AccountSpec("4300", "Discounts Given", Type.INCOME, Sub.OPERATING_REVENUE, "4000"),
    AccountSpec("4900", "Other Income", Type.INCOME, Sub.OTHER_INCOME, "4000"),
    # =========================================================================
    # 5xxx — Expenses
    # =========================================================================
    AccountSpec("5000", "Expenses", Type.EXPENSE, Sub.OPERATING_EXPENSE, is_group=True),
    AccountSpec(
        "5100",
        "Cost of Goods Sold",
        Type.EXPENSE,
        Sub.COST_OF_GOODS_SOLD,
        "5000",
        system_key=SystemAccount.COST_OF_GOODS_SOLD,
    ),
    AccountSpec("5200", "Operating Expenses", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5000", True),
    AccountSpec("5210", "Rent", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5220", "Electricity & Water", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5230", "Telephone & Internet", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5240", "Repairs & Maintenance", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5250", "Printing & Stationery", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5260", "Travel & Conveyance", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5270", "Professional Fees", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5280", "Bank Charges", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5290", "Marketing & Advertising", Type.EXPENSE, Sub.OPERATING_EXPENSE, "5200"),
    AccountSpec("5300", "Payroll", Type.EXPENSE, Sub.PAYROLL_EXPENSE, "5000", True),
    AccountSpec("5310", "Salaries & Wages", Type.EXPENSE, Sub.PAYROLL_EXPENSE, "5300"),
    AccountSpec("5320", "Employee Benefits", Type.EXPENSE, Sub.PAYROLL_EXPENSE, "5300"),
    AccountSpec("5400", "Depreciation", Type.EXPENSE, Sub.DEPRECIATION_EXPENSE, "5000"),
    AccountSpec("5500", "Rates & Taxes", Type.EXPENSE, Sub.TAX_EXPENSE, "5000"),
    # Absorbs sub-unit differences when an invoice total is rounded to the rupee.
    # Without a home for it, a one-paisa rounding leaves an entry unbalanced and
    # unpostable.
    AccountSpec(
        "5900",
        "Rounding Differences",
        Type.EXPENSE,
        Sub.OTHER_EXPENSE,
        "5000",
        system_key=SystemAccount.ROUNDING,
    ),
)


class JournalSpec(NamedTuple):
    code: str
    name: str
    journal_type: str
    number_prefix: str


#: One journal per posting source. Stage 3 and 4 resolve these by type.
DEFAULT_JOURNALS: Final[tuple[JournalSpec, ...]] = (
    JournalSpec("GEN", "General Journal", "general", "JV"),
    JournalSpec("SAL", "Sales Journal", "sales", "SI"),
    JournalSpec("PUR", "Purchase Journal", "purchase", "PI"),
    JournalSpec("CSH", "Cash Book", "cash", "CB"),
    JournalSpec("BNK", "Bank Book", "bank", "BB"),
    JournalSpec("OPN", "Opening Balances", "opening", "OB"),
)


def validate_template() -> None:
    """Assert the template is internally consistent.

    Called by a test rather than at import: a malformed chart should fail the
    build, not every request. Catches the mistakes that are easy to make when
    hand-editing a 60-line table — a duplicate code, a parent that does not
    exist, a parent defined after its child, a child whose type contradicts its
    parent's, or two accounts claiming the same system key.
    """
    seen: dict[str, AccountSpec] = {}
    system_keys: dict[str, str] = {}

    for spec in DEFAULT_CHART:
        if spec.code in seen:
            raise ValueError(f"duplicate account code {spec.code}")

        if spec.parent is not None:
            parent = seen.get(spec.parent)
            if parent is None:
                raise ValueError(
                    f"account {spec.code} references parent {spec.parent}, "
                    "which is undefined or defined later in the template"
                )
            if not parent.is_group:
                raise ValueError(
                    f"account {spec.code} has parent {spec.parent}, which is not a group"
                )
            if parent.account_type is not spec.account_type:
                raise ValueError(
                    f"account {spec.code} is {spec.account_type} but its parent "
                    f"{spec.parent} is {parent.account_type}"
                )

        if spec.system_key is not None:
            if spec.system_key in system_keys:
                raise ValueError(
                    f"system key {spec.system_key!r} claimed by both "
                    f"{system_keys[spec.system_key]} and {spec.code}"
                )
            if spec.is_group:
                raise ValueError(f"group account {spec.code} cannot hold a system key")
            system_keys[spec.system_key] = spec.code

        seen[spec.code] = spec
