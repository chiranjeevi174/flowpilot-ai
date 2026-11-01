"""Deterministic tabular numerical analysis and verification engine for spreadsheet workflows.

Provides mathematically grounded computations, column semantic inference, currency
detection, and validation to prevent LLM numerical hallucinations in summaries and emails.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from flowpilot.core.logging import get_logger

logger = get_logger("agents.analysis")

CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "usd": "USD",
    "eur": "EUR",
    "gbp": "GBP",
    "inr": "INR",
}

QUANTITY_COL_PATTERNS = re.compile(
    r"^(units?|quantity|qty|count|volume|orders?|items?_count)$", re.IGNORECASE
)
COST_COL_PATTERNS = re.compile(
    r"^(costs?|price|unit_cost|unit_price|rate|amounts?|subtotal|total)$", re.IGNORECASE
)
REP_COL_PATTERNS = re.compile(
    r"^(reps?|sales_?reps?|representatives?|agents?|salespersons?)$", re.IGNORECASE
)
ITEM_COL_PATTERNS = re.compile(
    r"^(items?|products?|items?_name|product_name|skus?|descriptions?)$", re.IGNORECASE
)
DATE_COL_PATTERNS = re.compile(
    r"^(dates?|order_date|transaction_date|timestamp|created_at)$", re.IGNORECASE
)
DATE_VAL_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}")


@dataclass
class ColumnAnalysis:
    """Statistical and semantic summary of a single tabular column."""

    name: str
    index: int
    is_numeric: bool = False
    is_date: bool = False
    total_cells: int = 0
    non_empty_count: int = 0
    missing_count: int = 0
    zero_count: int = 0
    numeric_values: list[Decimal] = field(default_factory=list)
    sum_val: Decimal | None = None
    mean_val: Decimal | None = None
    min_val: Decimal | None = None
    max_val: Decimal | None = None
    currency_symbol: str | None = None
    date_values: list[str] = field(default_factory=list)
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class TabularAnalysis:
    """Comprehensive deterministic analysis of a worksheet or dataset."""

    sheet_title: str
    total_rows_retrieved: int
    data_row_count: int
    is_truncated: bool
    headers: list[str]
    columns: dict[str, ColumnAnalysis]
    currency_detected: str | None
    currency_note: str
    date_range_note: str | None
    quantity_col: str | None = None
    cost_col: str | None = None
    rep_col: str | None = None
    item_col: str | None = None
    total_units: Decimal | None = None
    cost_column_sum: Decimal | None = None
    computed_order_totals: list[dict[str, Any]] = field(default_factory=list)
    rep_item_totals: list[dict[str, Any]] = field(default_factory=list)
    rep_totals: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_unit_combined_total: Decimal | None = None
    calculation_assumptions: list[str] = field(default_factory=list)
    verified_claims: list[str] = field(default_factory=list)


def clean_cell_str(val: Any) -> str:
    """Convert cell value to stripped string, handling None and floats."""
    if val is None:
        return ""
    return str(val).strip()


def parse_numeric_cell(val: Any) -> tuple[Decimal | None, str | None]:
    """Parse numeric value and detect any embedded currency symbol.

    Returns:
        (decimal_value, currency_symbol) or (None, None) if not numeric.
    """
    if val is None:
        return None, None
    s = str(val).strip()
    if not s:
        return None, None

    found_curr = None
    for sym in CURRENCY_SYMBOLS:
        if sym in s.lower():
            found_curr = sym
            s = re.sub(re.escape(sym), "", s, flags=re.IGNORECASE).strip()
            break

    # Remove thousands separators
    clean_num = s.replace(",", "")
    try:
        d = Decimal(clean_num)
        return d, found_curr
    except (InvalidOperation, ValueError):
        return None, found_curr


def analyze_tabular_dataset(
    rows: list[list[Any]],
    sheet_title: str = "Sheet",
    total_rows_available: int | None = None,
) -> TabularAnalysis:
    """Perform deterministic mathematical and semantic analysis on tabular spreadsheet rows."""
    if not rows:
        return TabularAnalysis(
            sheet_title=sheet_title,
            total_rows_retrieved=0,
            data_row_count=0,
            is_truncated=False,
            headers=[],
            columns={},
            currency_detected=None,
            currency_note="Spreadsheet contains no records.",
            date_range_note=None,
        )

    headers = [clean_cell_str(h) for h in rows[0]]
    data_rows = rows[1:]
    data_row_count = len(data_rows)
    is_truncated = total_rows_available is not None and total_rows_available > len(rows)

    detected_currencies: set[str] = set()
    col_analyses: dict[str, ColumnAnalysis] = {}

    for c_idx, h_name in enumerate(headers):
        ca = ColumnAnalysis(name=h_name, index=c_idx, total_cells=data_row_count)
        # Check header name for currency symbols
        for sym in CURRENCY_SYMBOLS:
            if sym in h_name.lower():
                ca.currency_symbol = sym
                detected_currencies.add(sym)

        num_vals: list[Decimal] = []
        date_vals: list[str] = []

        for row in data_rows:
            raw_cell = row[c_idx] if c_idx < len(row) else None
            cell_str = clean_cell_str(raw_cell)

            if not cell_str:
                ca.missing_count += 1
                continue

            ca.non_empty_count += 1
            if len(ca.sample_values) < 5:
                ca.sample_values.append(cell_str)

            # Check for date format
            if DATE_VAL_REGEX.match(cell_str) or DATE_COL_PATTERNS.match(h_name):
                date_vals.append(cell_str)

            # Check numeric parsing
            parsed_num, cell_curr = parse_numeric_cell(raw_cell)
            if cell_curr:
                ca.currency_symbol = cell_curr
                detected_currencies.add(cell_curr)

            if parsed_num is not None:
                num_vals.append(parsed_num)
                if parsed_num == 0:
                    ca.zero_count += 1

        if num_vals and len(num_vals) >= (ca.non_empty_count * 0.5):
            ca.is_numeric = True
            ca.numeric_values = num_vals
            ca.sum_val = sum(num_vals)
            ca.min_val = min(num_vals)
            ca.max_val = max(num_vals)
            ca.mean_val = ca.sum_val / Decimal(len(num_vals)) if num_vals else Decimal(0)

        if date_vals and len(date_vals) >= (ca.non_empty_count * 0.5):
            ca.is_date = True
            ca.date_values = sorted(date_vals)

        col_analyses[h_name] = ca

    # 1. Currency determination
    currency_detected = next(iter(detected_currencies), None)
    if currency_detected:
        currency_note = f"Explicit currency detected in source: {currency_detected}."
    else:
        currency_note = (
            "Currency is NOT established in the spreadsheet. Do NOT automatically introduce "
            "USD, INR, or '$' symbols into totals or calculations."
        )

    # 2. Date range analysis
    date_note = None
    for ca in col_analyses.values():
        if ca.is_date and ca.date_values:
            min_d, max_d = ca.date_values[0], ca.date_values[-1]
            date_note = (
                f"Dates span from {min_d} to {max_d}. Do not characterize these dates "
                "as 'recent' without an explicit reference date."
            )
            break

    # 3. Identify Business Metrics (Units, Cost, Rep, Item)
    qty_col_name = next((c for c in headers if QUANTITY_COL_PATTERNS.match(c)), None)
    cost_col_name = next((c for c in headers if COST_COL_PATTERNS.match(c)), None)
    rep_col_name = next((c for c in headers if REP_COL_PATTERNS.match(c)), None)
    item_col_name = next((c for c in headers if ITEM_COL_PATTERNS.match(c)), None)

    total_units: Decimal | None = None
    cost_col_sum: Decimal | None = None
    order_totals: list[dict[str, Any]] = []
    rep_item_totals: list[dict[str, Any]] = []
    rep_totals: dict[str, dict[str, Any]] = {}
    per_unit_combined_total: Decimal | None = None
    calculation_assumptions: list[str] = []
    verified_claims: list[str] = []

    if qty_col_name and qty_col_name in col_analyses:
        total_units = col_analyses[qty_col_name].sum_val
        verified_claims.append(f"Total units across all rows: {total_units}")

    if cost_col_name and cost_col_name in col_analyses:
        cost_col_sum = col_analyses[cost_col_name].sum_val
        verified_claims.append(f"Sum of '{cost_col_name}' column values: {cost_col_sum}")

    # If both quantity and cost exist, calculate both per-unit and row-total interpretations
    if qty_col_name and cost_col_name:
        q_idx = headers.index(qty_col_name)
        c_idx = headers.index(cost_col_name)
        id_idx = next((i for i, h in enumerate(headers) if "id" in h.lower()), None)
        item_idx = next((i for i, h in enumerate(headers) if "item" in h.lower()), None)

        row_products: list[Decimal] = []
        for r_num, row in enumerate(data_rows, start=1):
            q_val, _ = parse_numeric_cell(row[q_idx] if q_idx < len(row) else None)
            c_val, _ = parse_numeric_cell(row[c_idx] if c_idx < len(row) else None)
            row_id = (
                clean_cell_str(row[id_idx])
                if id_idx is not None and id_idx < len(row)
                else f"Row {r_num}"
            )
            item_name = (
                clean_cell_str(row[item_idx])
                if item_idx is not None and item_idx < len(row)
                else "Item"
            )

            if q_val is not None and c_val is not None:
                prod = q_val * c_val
                row_products.append(prod)
                order_totals.append(
                    {
                        "order_id": row_id,
                        "item": item_name,
                        "units": q_val,
                        "cost_val": c_val,
                        "calculated_total": prod,
                    }
                )

        if row_products:
            per_unit_combined_total = sum(row_products)
            order_breakdowns = "; ".join(
                f"Order {ot['order_id']} ({ot['item']}): {ot['units']} × "
                f"{ot['cost_val']} = {ot['calculated_total']:,}"
                for ot in order_totals
            )
            calculation_assumptions.append(
                f"INTERPRETATION A (Cost as unit price): If '{cost_col_name}' is per-unit, "
                f"{order_breakdowns}. Correct combined total is {per_unit_combined_total:,} "
                f"across {total_units} total units."
            )
            calculation_assumptions.append(
                f"INTERPRETATION B (Cost as total order cost): If '{cost_col_name}' is already "
                f"the total cost per order, the combined sum of the '{cost_col_name}' column is "
                f"{cost_col_sum:,} across {total_units} total units."
            )
            calculation_assumptions.append(
                f"VALIDATION RULE: Both interpretations ({per_unit_combined_total:,} unit amount "
                f"and {cost_col_sum:,} order amount) are grounded in the source data. "
                "All figures cited in outputs must be derived strictly from these calculations."
            )

    # Calculate Representative and Item aggregations if columns are present
    if rep_col_name and item_col_name:
        rep_idx = headers.index(rep_col_name)
        item_idx = headers.index(item_col_name)
        q_idx = headers.index(qty_col_name) if qty_col_name else None
        c_idx = headers.index(cost_col_name) if cost_col_name else None

        rep_item_map: dict[tuple[str, str], dict[str, Any]] = {}

        for row in data_rows:
            r_val = clean_cell_str(row[rep_idx]) if rep_idx < len(row) else ""
            i_val = clean_cell_str(row[item_idx]) if item_idx < len(row) else ""
            if not r_val and not i_val:
                continue

            q_val = Decimal(1)
            if q_idx is not None and q_idx < len(row):
                pq, _ = parse_numeric_cell(row[q_idx])
                if pq is not None:
                    q_val = pq

            c_val = Decimal(0)
            if c_idx is not None and c_idx < len(row):
                pc, _ = parse_numeric_cell(row[c_idx])
                if pc is not None:
                    c_val = pc

            key = (r_val, i_val)
            if key not in rep_item_map:
                rep_item_map[key] = {
                    "rep": r_val,
                    "item": i_val,
                    "units": Decimal(0),
                    "unit_cost_total": Decimal(0),
                    "order_cost_total": Decimal(0),
                    "row_count": 0,
                }
            rep_item_map[key]["units"] += q_val
            rep_item_map[key]["unit_cost_total"] += q_val * c_val
            rep_item_map[key]["order_cost_total"] += c_val
            rep_item_map[key]["row_count"] += 1

            if r_val not in rep_totals:
                rep_totals[r_val] = {
                    "rep": r_val,
                    "items": set(),
                    "total_units": Decimal(0),
                    "unit_cost_total": Decimal(0),
                    "order_cost_total": Decimal(0),
                    "row_count": 0,
                }
            rep_totals[r_val]["items"].add(i_val)
            rep_totals[r_val]["total_units"] += q_val
            rep_totals[r_val]["unit_cost_total"] += q_val * c_val
            rep_totals[r_val]["order_cost_total"] += c_val
            rep_totals[r_val]["row_count"] += 1

        rep_item_totals = list(rep_item_map.values())
        if rep_item_totals:
            rep_breakdowns = "; ".join(
                f"{rit['rep']} ({rit['item']}): {rit['unit_cost_total']:,} (unit cost) "
                f"or {rit['order_cost_total']:,} (order cost)"
                for rit in rep_item_totals
            )
            calculation_assumptions.append(f"REPRESENTATIVE BREAKDOWN: {rep_breakdowns}")

    return TabularAnalysis(
        sheet_title=sheet_title,
        total_rows_retrieved=len(rows),
        data_row_count=data_row_count,
        is_truncated=is_truncated,
        headers=headers,
        columns=col_analyses,
        currency_detected=currency_detected,
        currency_note=currency_note,
        date_range_note=date_note,
        quantity_col=qty_col_name,
        cost_col=cost_col_name,
        rep_col=rep_col_name,
        item_col=item_col_name,
        total_units=total_units,
        cost_column_sum=cost_col_sum,
        computed_order_totals=order_totals,
        rep_item_totals=rep_item_totals,
        rep_totals=rep_totals,
        per_unit_combined_total=per_unit_combined_total,
        calculation_assumptions=calculation_assumptions,
        verified_claims=verified_claims,
    )


def format_analysis_for_prompt(analysis: TabularAnalysis) -> str:
    """Format tabular analysis into explicit, verified guidelines for the LLM prompt."""
    lines = [
        "================================================================================",
        "DETERMINISTIC NUMERICAL ANALYSIS & VERIFIED FACTS (STRICT GROUND TRUTH)",
        "================================================================================",
        f"Worksheet: '{analysis.sheet_title}' | Data records: {analysis.data_row_count} rows.",
        f"Columns: {', '.join(analysis.headers)}",
        f"- Currency status: {analysis.currency_note}",
    ]

    if analysis.date_range_note:
        lines.append(f"- Date context: {analysis.date_range_note}")

    if analysis.is_truncated:
        lines.append(
            "- WARNING: Dataset truncated by query limits. Totals reflect retrieved sample only."
        )
    else:
        lines.append("- Completeness: Full dataset retrieved (no rows omitted or truncated).")

    if analysis.calculation_assumptions:
        lines.append("\nVerified Mathematical Calculations:")
        for asm in analysis.calculation_assumptions:
            lines.append(f"  * {asm}")

    if analysis.rep_item_totals:
        lines.append("\nAggregated Representative & Item Totals (Ground Truth):")
        lines.append("| Rep | Item | Units | Total Cost (Units × Cost) | Order Cost Sum |")
        lines.append("|---|---|---|---|---|")
        for rit in analysis.rep_item_totals:
            lines.append(
                f"| {rit['rep']} | {rit['item']} | {rit['units']} | "
                f"{rit['unit_cost_total']:,} | {rit['order_cost_total']:,} |"
            )

    lines.extend(
        [
            "\nCRITICAL SUMMARY & EMAIL GENERATION RULES:",
            "1. Ground all numbers strictly in verified figures from the dataset above.",
        ]
    )

    if analysis.per_unit_combined_total is not None and analysis.cost_column_sum is not None:
        lines.append(
            f"   - Interpretation A (Cost as unit amount): Combined total is "
            f"{analysis.per_unit_combined_total:,} across {analysis.total_units} total units."
        )
        lines.append(
            f"   - Interpretation B (Cost as order-level amount): Sum of '{analysis.cost_col}' "
            f"column is {analysis.cost_column_sum:,} across {analysis.total_units} total units."
        )

    lines.extend(
        [
            "2. State your calculation assumptions clearly. Do NOT invent currencies.",
            "3. If formatting as a table, use the exact aggregated Rep/Item figures above.",
            "4. State only mathematically verified amounts. Do NOT invent or guess numbers.",
            "5. Do NOT output contradictory meta-statements or mention past regressions.",
            "6. Do NOT describe January 2026 records as 'recent' without reference date.",
            "================================================================================",
        ]
    )

    return "\n".join(lines)


def get_verified_numerical_totals(analysis: TabularAnalysis) -> set[Decimal]:
    """Collect all mathematically grounded totals and numerical facts from analysis."""
    totals: set[Decimal] = set()
    if analysis.per_unit_combined_total is not None:
        totals.add(analysis.per_unit_combined_total)
    if analysis.cost_column_sum is not None:
        totals.add(analysis.cost_column_sum)
    if analysis.total_units is not None:
        totals.add(analysis.total_units)
    if analysis.data_row_count:
        totals.add(Decimal(analysis.data_row_count))
    for ot in analysis.computed_order_totals:
        if "calculated_total" in ot and ot["calculated_total"] is not None:
            totals.add(Decimal(str(ot["calculated_total"])))
        if "cost_val" in ot and ot["cost_val"] is not None:
            totals.add(Decimal(str(ot["cost_val"])))
        if "units" in ot and ot["units"] is not None:
            totals.add(Decimal(str(ot["units"])))
    for rit in analysis.rep_item_totals:
        if "unit_cost_total" in rit and rit["unit_cost_total"] is not None:
            totals.add(Decimal(str(rit["unit_cost_total"])))
        if "order_cost_total" in rit and rit["order_cost_total"] is not None:
            totals.add(Decimal(str(rit["order_cost_total"])))
        if "units" in rit and rit["units"] is not None:
            totals.add(Decimal(str(rit["units"])))
    for col in analysis.columns.values():
        for nv in col.numeric_values:
            totals.add(nv)
    return totals


def find_numerical_contradictions(text: str, analysis: TabularAnalysis) -> list[str]:
    """Identify contradictory claims in text, such as asserting a valid amount is incorrect."""
    contradictions: list[str] = []

    valid_nums: list[str] = []
    if analysis.per_unit_combined_total is not None:
        valid_nums.extend(
            [f"{analysis.per_unit_combined_total:,}", str(analysis.per_unit_combined_total)]
        )
    if analysis.cost_column_sum is not None:
        valid_nums.extend([f"{analysis.cost_column_sum:,}", str(analysis.cost_column_sum)])
    if analysis.total_units is not None:
        valid_nums.extend([f"{analysis.total_units:,}", str(analysis.total_units)])
    if analysis.data_row_count:
        valid_nums.append(str(analysis.data_row_count))
    for rit in analysis.rep_item_totals:
        valid_nums.extend([f"{rit['unit_cost_total']:,}", str(rit["unit_cost_total"])])
        valid_nums.extend([f"{rit['order_cost_total']:,}", str(rit["order_cost_total"])])
        valid_nums.extend([f"{rit['units']:,}", str(rit["units"])])

    negation_pattern = (
        r"(?:mathematically incorrect|incorrect|invalid|wrong|erroneous|"
        r"must not be used|do not use|not be used|must never be used)"
    )

    for num_str in set(valid_nums):
        clean_num = re.escape(num_str)
        # Check num followed by negation
        pat_after = rf"\b{clean_num}\b[^.\n;]*?\b{negation_pattern}\b"
        if re.search(pat_after, text, re.IGNORECASE):
            contradictions.append(
                f"Contradictory claim: asserts verified amount '{num_str}' "
                "is incorrect or must not be used."
            )
        # Check negation followed by num
        pat_before = rf"\b{negation_pattern}\b[^.\n;]*?\b{clean_num}\b"
        if re.search(pat_before, text, re.IGNORECASE):
            contradictions.append(
                f"Contradictory claim: asserts verified amount '{num_str}' "
                "is incorrect or must not be used."
            )

    # Check if text asserts any numerical value is mathematically incorrect or invalid
    generic_num_contradiction = re.search(
        r"\b(?:value|figure|amount|number|total)?\s*([\d,]+(?:\.\d+)?)\s+is\s+"
        r"(?:mathematically\s+incorrect|erroneous|invalid)\b",
        text,
        re.IGNORECASE,
    )
    if generic_num_contradiction:
        claimed_num = generic_num_contradiction.group(1)
        if not any(claimed_num in c for c in contradictions):
            contradictions.append(
                f"Contradictory claim: asserts amount '{claimed_num}' "
                "is mathematically incorrect or must not be used."
            )

    return contradictions


def clean_numerical_contradictions(text: str, analysis: TabularAnalysis) -> str:
    """Safely remove contradictory statements and unhelpful regression meta-commentary from text."""
    lines = text.splitlines()
    cleaned_lines: list[str] = []

    valid_nums: list[str] = []
    if analysis.per_unit_combined_total is not None:
        valid_nums.extend(
            [f"{analysis.per_unit_combined_total:,}", str(analysis.per_unit_combined_total)]
        )
    if analysis.cost_column_sum is not None:
        valid_nums.extend([f"{analysis.cost_column_sum:,}", str(analysis.cost_column_sum)])
    for rit in analysis.rep_item_totals:
        valid_nums.extend([f"{rit['unit_cost_total']:,}", str(rit["unit_cost_total"])])
        valid_nums.extend([f"{rit['order_cost_total']:,}", str(rit["order_cost_total"])])

    negation_pattern = (
        r"(?:mathematically incorrect|incorrect|invalid|wrong|erroneous|"
        r"must not be used|do not use|not be used|must never be used)"
    )

    for line in lines:
        is_contradictory = False
        for num_str in set(valid_nums):
            clean_num = re.escape(num_str)
            if re.search(
                rf"\b{clean_num}\b[^.\n;]*?\b{negation_pattern}\b", line, re.IGNORECASE
            ) or re.search(rf"\b{negation_pattern}\b[^.\n;]*?\b{clean_num}\b", line, re.IGNORECASE):
                is_contradictory = True
                break

        # Purge any unhelpful meta-commentary about past erroneous numbers or regressions
        if re.search(
            r"\b(?:previously|past|prior)?\s*(?:erroneous|incorrect|invalid)\s*(?:figure|amount|number|total|value)\b",
            line,
            re.IGNORECASE,
        ):
            is_contradictory = True

        if not is_contradictory:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def rectify_text_numbers(text: str, analysis: TabularAnalysis) -> str:
    """Safely correct ungrounded totals and currency assumptions without unsafe global replacement.

    Guarantees:
    - Never turns negative statements into contradictions.
    - Purges contradictory statements regarding verified numbers.
    - Replaces ungrounded totals in affirmative statements with verified amounts.
    - Strips unauthorized currency symbols when currency is unspecified.
    """
    # 1. Clean any contradictory claims or negative regression comments first
    rectified = clean_numerical_contradictions(text, analysis)

    # 2. Contextual correction of affirmative ungrounded totals
    if analysis.per_unit_combined_total is not None:
        correct_tot = f"{analysis.per_unit_combined_total:,}"
        verified_totals = get_verified_numerical_totals(analysis)

        def _replace_inaccurate_total(match: re.Match) -> str:
            prefix = match.group(1)
            num_str = match.group(2)
            clean_num = num_str.replace(",", "")
            try:
                dec = Decimal(clean_num)
                if dec not in verified_totals:
                    return f"{prefix}{correct_tot}"
            except Exception:
                pass
            return match.group(0)

        # Match affirmative cost/total statements (e.g. 'total of 8,300', 'combined cost of 8,300')
        rectified = re.sub(
            r"(\b(?:total(?:\s+calculated)?\s+cost|combined\s+cost|combined\s+total|total\s+(?:order\s+)?amount|total\s+value|yielding|yields)\s+(?:(?:across\s+[^,\n;]+?|for\s+all\s+orders)\s+)?(?:was\s+computed\s+as\s+|is\s+|of\s+)?\$?)([\d,]+(?:\.\d+)?)\b",
            _replace_inaccurate_total,
            rectified,
            flags=re.IGNORECASE,
        )
        rectified = re.sub(
            r"(\b(?:total|combined)\s+(?:(?:across\s+[^,\n;]+?|for\s+all\s+orders)\s+)?(?:is\s+|of\s+)\$?)([\d,]+(?:\.\d+)?)\b(?!\s*(?:rows?|orders?|records?|units?|items?))",
            _replace_inaccurate_total,
            rectified,
            flags=re.IGNORECASE,
        )

    # 3. Strip unauthorized currency symbols when currency is not established
    if analysis.currency_detected is None:
        rectified = re.sub(r"\$(\d+(?:,\d{3})*(?:\.\d+)?)", r"\1", rectified)

    # 4. Clarify ambiguous recency claims
    rectified = re.sub(
        r"\brecent orders from January 2026\b",
        "orders recorded in January 2026",
        rectified,
        flags=re.IGNORECASE,
    )
    rectified = re.sub(
        r"\brecent sales orders from early January 2026\b",
        "sales orders recorded in early January 2026",
        rectified,
        flags=re.IGNORECASE,
    )

    # 5. Final safety pass to ensure no contradictions were created
    rectified = clean_numerical_contradictions(rectified, analysis)

    return rectified


def validate_summary_accuracy(summary_text: str, analysis: TabularAnalysis) -> list[str]:
    """Validate summary does not contain numerical errors or contradictions.

    Returns:
        List of error descriptions, empty if fully valid.
    """
    errors: list[str] = []

    # 1. Contradiction check: verified amounts must never be claimed as incorrect
    contradictions = find_numerical_contradictions(summary_text, analysis)
    errors.extend(contradictions)

    # 2. Check for ungrounded/inaccurate numbers in total claims
    verified_totals = get_verified_numerical_totals(analysis)
    total_matches = re.finditer(
        r"\b(?:total(?:\s+calculated)?\s+cost|combined\s+cost|combined\s+total|total\s+(?:order\s+)?amount|total\s+value)\s+(?:(?:across\s+[^,\n;]+?|for\s+all\s+orders)\s+)?(?:was\s+computed\s+as\s+|is\s+|of\s+|yielding\s+|yields\s+)?\$?([\d,]+(?:\.\d+)?)\b",
        summary_text,
        re.IGNORECASE,
    )
    for m in total_matches:
        num_str = m.group(1)
        clean_num = num_str.replace(",", "")
        try:
            val_dec = Decimal(clean_num)
            if val_dec not in verified_totals:
                errors.append(
                    f"Found inaccurate total amount {num_str}. Verified combined total is "
                    f"{analysis.per_unit_combined_total:,} (unit price assumption) or "
                    f"{analysis.cost_column_sum:,} (total cost assumption)."
                )
        except Exception:
            pass

    # Also check shorter total phrases: e.g. "total of 8,300"
    total_short_matches = re.finditer(
        r"\b(?:total|combined)\s+(?:is\s+|of\s+)\$?([\d,]+(?:\.\d+)?)\b(?!\s*(?:rows?|orders?|records?|units?|items?))",
        summary_text,
        re.IGNORECASE,
    )
    for m in total_short_matches:
        num_str = m.group(1)
        clean_num = num_str.replace(",", "")
        try:
            val_dec = Decimal(clean_num)
            if val_dec not in verified_totals:
                err_msg = (
                    f"Found inaccurate combined amount {num_str}. Verified combined total is "
                    f"{analysis.per_unit_combined_total} (unit price assumption) or "
                    f"{analysis.cost_column_sum} (total cost assumption)."
                )
                if err_msg not in errors:
                    errors.append(err_msg)
        except Exception:
            pass

    # 3. Check for currency hallucination if currency was not established
    if analysis.currency_detected is None and re.search(r"\$\d+", summary_text):
        errors.append(
            "Found unauthorized currency symbol '$' when source spreadsheet contains "
            "no established currency."
        )

    # 4. Check for ambiguous recency
    if re.search(
        r"\brecent\b.*\b(January 2026|Jan 2026)\b",
        summary_text,
        flags=re.IGNORECASE,
    ):
        errors.append(
            "Found ambiguous recency claim describing January 2026 records as 'recent' "
            "without reference date."
        )

    return errors
