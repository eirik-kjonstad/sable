"""Rule registry for sable check mode."""

from __future__ import annotations

from ..diagnostics import Rule
from .formatting import (
    SBL001RelationalOperatorRule,
    SBL002EndKeywordFormRule,
    SBL003DeclarationDoubleColonRule,
    SBL004SemicolonSplitRule,
    SBL005TrailingWhitespaceRule,
    SBL009TabIndentationRule,
    SBL010StrayLeadingContinuationRule,
    SBL101MissingImplicitNoneRule,
    SBL102MissingImplicitNoneProcedureRule,
    SBL103MissingIntentOnDummyArgsRule,
)

_ALL_RULES: tuple[Rule, ...] = (
    SBL001RelationalOperatorRule(),
    SBL002EndKeywordFormRule(),
    SBL003DeclarationDoubleColonRule(),
    SBL004SemicolonSplitRule(),
    SBL005TrailingWhitespaceRule(),
    SBL009TabIndentationRule(),
    SBL010StrayLeadingContinuationRule(),
    SBL101MissingImplicitNoneRule(),
    SBL102MissingImplicitNoneProcedureRule(),
    SBL103MissingIntentOnDummyArgsRule(),
)


def get_rules(
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    rule_set: str = "all",
) -> tuple[Rule, ...]:
    """Return rules after applying select/ignore/rule-set filters."""
    selected = None if not select else {rule_id.upper() for rule_id in select}
    ignored = set() if not ignore else {rule_id.upper() for rule_id in ignore}
    selected_rule_set = rule_set.strip().lower()
    if selected_rule_set not in {"all", "style", "lint"}:
        selected_rule_set = "all"

    style_rule_ids = {
        "SBL001",
        "SBL002",
        "SBL003",
        "SBL004",
        "SBL005",
        "SBL009",
        "SBL010",
    }
    lint_rule_ids = {"SBL101", "SBL102", "SBL103"}

    out = []
    for rule in _ALL_RULES:
        code = rule.rule_id.upper()
        if selected is not None and code not in selected:
            continue
        if selected is None:
            if selected_rule_set == "style" and code not in style_rule_ids:
                continue
            if selected_rule_set == "lint" and code not in lint_rule_ids:
                continue
        if code in ignored:
            continue
        out.append(rule)
    return tuple(out)


def get_rule_summaries() -> dict[str, str]:
    """Return map of rule id -> human-readable summary."""
    return {rule.rule_id.upper(): rule.summary for rule in _ALL_RULES}
