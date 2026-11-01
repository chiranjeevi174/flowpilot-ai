"""Parameter and placeholder resolution utilities for multi-agent workflows."""

import json
import re
from typing import Any

from flowpilot.agents.analysis import analyze_tabular_dataset, format_analysis_for_prompt
from flowpilot.core.logging import get_logger

logger = get_logger("agents.resolution")

STEP_REF_REGEX = re.compile(
    r"(?:output_from_step_(\d+)|\{step_(\d+)\.output\}|\{output_from_step_(\d+)\}|\$step_(\d+)|step_(\d+)_output)",
    re.IGNORECASE,
)


def format_step_output_as_text(result: Any) -> str:
    """Format structured step results into human/LLM-readable text."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        # 1. Google Sheets multi-worksheet result
        if "worksheets" in result:
            lines = [f"Spreadsheet ID: {result.get('spreadsheet_id', 'Unknown')}"]
            analysis_blocks: list[str] = []

            for ws in result.get("worksheets", []):
                title = ws.get("sheet_title", "Sheet")
                row_count = ws.get("row_count", 0)
                is_empty = ws.get("is_empty", False)
                lines.append(f"\n--- Worksheet: '{title}' ({row_count} rows) ---")
                if is_empty or row_count == 0:
                    lines.append("(Empty worksheet)")
                    continue
                rows = ws.get("rows", [])
                if rows:
                    headers = rows[0]
                    lines.append("Headers: " + " | ".join(str(h) for h in headers))
                    for r in rows[1:51]:  # show up to 50 rows in prompt
                        lines.append(" | ".join(str(c) for c in r))
                    if len(rows) > 51:
                        lines.append(f"... and {len(rows) - 51} more rows")

                    # Perform deterministic numerical analysis
                    tabular_analysis = analyze_tabular_dataset(
                        rows=rows,
                        sheet_title=title,
                        total_rows_available=ws.get("total_rows_available"),
                    )
                    analysis_blocks.append(format_analysis_for_prompt(tabular_analysis))

            if analysis_blocks:
                lines.append("\n" + "\n\n".join(analysis_blocks))

            return "\n".join(lines)

        # 2. Google Sheets single-range result
        if "rows" in result and isinstance(result["rows"], list):
            rows = result["rows"]
            lines = [f"Spreadsheet Range: {result.get('range', 'Unknown')} ({len(rows)} rows)"]
            if not rows:
                lines.append("(No rows found)")
            else:
                lines.append("Headers: " + " | ".join(str(h) for h in rows[0]))
                for r in rows[1:51]:
                    lines.append(" | ".join(str(c) for c in r))
                if len(rows) > 51:
                    lines.append(f"... and {len(rows) - 51} more rows")

                tabular_analysis = analyze_tabular_dataset(
                    rows=rows,
                    sheet_title=result.get("range", "Range"),
                )
                lines.append("\n" + format_analysis_for_prompt(tabular_analysis))

            return "\n".join(lines)

        # 3. Task summary result
        if "summary" in result:
            parts = [f"Executive Summary:\n{result.get('summary')}"]
            highlights = result.get("key_highlights")
            if highlights:
                if isinstance(highlights, list):
                    parts.append("\nKey Highlights:\n" + "\n".join(f"- {h}" for h in highlights))
                else:
                    parts.append(f"\nKey Highlights:\n{highlights}")
            next_steps = result.get("next_steps")
            if next_steps:
                if isinstance(next_steps, list):
                    parts.append("\nNext Steps:\n" + "\n".join(f"- {s}" for s in next_steps))
                else:
                    parts.append(f"\nNext Steps:\n{next_steps}")
            return "\n".join(parts)

        # 4. Response drafting result
        if "body" in result:
            return str(result.get("body", ""))

        # 5. Generic dictionary
        try:
            return json.dumps(result, indent=2, default=str)
        except Exception:
            return str(result)

    if isinstance(result, list):
        try:
            return json.dumps(result, indent=2, default=str)
        except Exception:
            return str(result)

    return str(result)


def find_step_result(step_results: list[dict[str, Any]], step_num: int) -> dict[str, Any] | None:
    """Find a step result by step number (e.g. 1 -> 'step_1' or 1st element)."""
    target_id = f"step_{step_num}"
    for r in step_results:
        if r.get("step_id") == target_id:
            return r
    if 1 <= step_num <= len(step_results):
        return step_results[step_num - 1]
    return None


def resolve_step_placeholders(
    parameters: dict[str, Any],
    step_results: list[dict[str, Any]],
    user_email: str | None = None,
    operation: str = "",
) -> dict[str, Any]:
    """Resolve references like 'output_from_step_1' into actual preceding step outputs.

    Also populates missing required parameters like recipient, email body, or context
    from preceding steps if available.
    """
    resolved = dict(parameters)

    # 1. Substitute explicit placeholder strings in parameter values
    for key, val in list(resolved.items()):
        if not isinstance(val, str):
            continue

        match = STEP_REF_REGEX.search(val)
        if match:
            # Extract which group matched
            step_num_str = next(g for g in match.groups() if g is not None)
            step_num = int(step_num_str)
            found = find_step_result(step_results, step_num)
            if found:
                actual_result = found.get("result")
                # If the entire value was the placeholder
                if val.strip() == match.group(0):
                    if key in ("text", "context", "body", "input", "message"):
                        resolved[key] = format_step_output_as_text(actual_result)
                    else:
                        resolved[key] = actual_result
                else:
                    # Partial string substitution
                    text_rep = format_step_output_as_text(actual_result)
                    resolved[key] = val.replace(match.group(0), text_rep)
            else:
                logger.warning(
                    "Step placeholder '%s' referenced step_%d which has not completed yet",
                    val,
                    step_num,
                )

    # 2. Context / Text propagation for analysis steps
    if (
        operation in ("task_summary_generation", "response_drafting", "information_extraction")
        and not resolved.get("text")
        and not resolved.get("context")
        and step_results
    ):
        latest = step_results[-1]
        resolved["text"] = format_step_output_as_text(latest.get("result"))

    # 3. Gmail send email parameter completion
    if operation.startswith("gmail_"):
        # Recipient resolution: preserve explicit email if supplied in either recipient or to
        recip_cand = str(resolved.get("recipient") or "").strip()
        to_cand = str(resolved.get("to") or "").strip()

        def is_explicit_email(val: str) -> bool:
            return bool(
                val
                and "@" in val
                and "." in val
                and val.lower() not in ("authenticated_user", "user", "me", "self", "none", "null")
            )

        if is_explicit_email(recip_cand):
            resolved["recipient"] = recip_cand
        elif is_explicit_email(to_cand):
            resolved["recipient"] = to_cand
        elif user_email:
            resolved["recipient"] = user_email
            logger.info("Resolved default recipient to user email: %s", user_email)

        # Body resolution
        current_body = resolved.get("body") or resolved.get("message")
        is_empty_or_placeholder = (
            not current_body
            or str(current_body).strip() in ("", "None", "null")
            or "output_from_step" in str(current_body)
        )
        if is_empty_or_placeholder:
            # Find the latest text/summary result from step_results
            for r in reversed(step_results):
                res = r.get("result")
                if res:
                    body_candidate = format_step_output_as_text(res)
                    if body_candidate:
                        resolved["body"] = body_candidate
                        break

        # Subject resolution
        if not resolved.get("subject") or str(resolved.get("subject")).strip() in ("", "None"):
            # Check if any step result has a subject
            for r in reversed(step_results):
                res = r.get("result")
                if isinstance(res, dict) and res.get("subject"):
                    resolved["subject"] = res.get("subject")
                    break
            if not resolved.get("subject"):
                resolved["subject"] = "FlowPilot Workflow Summary"

    return resolved
