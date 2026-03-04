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
)


def get_rules(
    *, select: set[str] | None = None, ignore: set[str] | None = None
) -> tuple[Rule, ...]:
    """Return rules after applying select/ignore filters."""
    selected = None if not select else {rule_id.upper() for rule_id in select}
    ignored = set() if not ignore else {rule_id.upper() for rule_id in ignore}
    out = []
    for rule in _ALL_RULES:
        code = rule.rule_id.upper()
        if selected is not None and code not in selected:
            continue
        if code in ignored:
            continue
        out.append(rule)
    return tuple(out)
