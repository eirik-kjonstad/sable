"""Formatting related check rules with safe autofixes."""

from __future__ import annotations

import bisect
import re

from ..diagnostics import (
    Diagnostic,
    Fix,
    FixSafety,
    RuleContext,
    Severity,
    TextEdit,
)
from ..formatter import (
    _COMPACT_TO_SPACED,
    _canonicalise_declaration_tokens,
    _parse_declaration,
    _render_tokens,
)
from ..tokens import Token, TokenKind

_OLD_TO_NEW_REL_OP: dict[str, str] = {
    ".eq.": "==",
    ".ne.": "/=",
    ".lt.": "<",
    ".le.": "<=",
    ".gt.": ">",
    ".ge.": ">=",
}

_REL_OP_KINDS = {
    TokenKind.OP_EQ,
    TokenKind.OP_NEQ,
    TokenKind.OP_LT,
    TokenKind.OP_LE,
    TokenKind.OP_GT,
    TokenKind.OP_GE,
}

_SPACED_END_TO_COMPACT: dict[tuple[str, ...], str] = {
    tuple(spaced.split()): compact
    for compact, spaced in _COMPACT_TO_SPACED.items()
    if spaced.startswith("end ")
}


def _token_start(ctx: RuleContext, tok: Token) -> int:
    return ctx.line_starts[tok.line - 1] + tok.col - 1


def _token_end(ctx: RuleContext, tok: Token) -> int:
    return _token_start(ctx, tok) + len(tok.text)


def _offset_to_line_col(ctx: RuleContext, offset: int) -> tuple[int, int]:
    idx = bisect.bisect_right(ctx.line_starts, offset) - 1
    idx = max(0, min(idx, len(ctx.line_starts) - 1))
    line = idx + 1
    col = (offset - ctx.line_starts[idx]) + 1
    return line, col


def _keyword_case(text: str, case: str) -> str:
    return text.upper() if case == "upper" else text.lower()


class SBL001RelationalOperatorRule:
    """Replace old-style relational operators (.EQ., .NE., ...) with modern ones."""

    rule_id = "SBL001"
    summary = "Old-style relational operator can be modernized."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        if not ctx.cfg.normalize_operators:
            return []

        diagnostics: list[Diagnostic] = []
        for tok in ctx.tokens:
            if tok.kind not in _REL_OP_KINDS:
                continue
            replacement = _OLD_TO_NEW_REL_OP.get(tok.text.lower())
            if replacement is None:
                continue
            start = _token_start(ctx, tok)
            end = _token_end(ctx, tok)
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=tok.line,
                    col=tok.col,
                    end_line=tok.line,
                    end_col=tok.col + len(tok.text),
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message=f"Replace {tok.text} with {replacement}",
                        edits=(
                            TextEdit(start=start, end=end, replacement=replacement),
                        ),
                    ),
                )
            )
        return diagnostics


class SBL002EndKeywordFormRule:
    """Normalize END keyword form to configured compact/spaced style."""

    rule_id = "SBL002"
    summary = "END keyword form differs from configured style."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        tokens = ctx.tokens

        if ctx.cfg.end_keyword_form == "spaced":
            for tok in tokens:
                if tok.kind != TokenKind.KEYWORD:
                    continue
                compact = tok.text.lower()
                spaced = _COMPACT_TO_SPACED.get(compact)
                if spaced is None:
                    continue
                replacement = _keyword_case(spaced, ctx.cfg.keyword_case)
                start = _token_start(ctx, tok)
                end = _token_end(ctx, tok)
                diagnostics.append(
                    Diagnostic(
                        rule_id=self.rule_id,
                        message=self.summary,
                        line=tok.line,
                        col=tok.col,
                        end_line=tok.line,
                        end_col=tok.col + len(tok.text),
                        severity=Severity.WARNING,
                        path=ctx.path,
                        fix=Fix(
                            message=f"Replace {tok.text} with {replacement}",
                            edits=(
                                TextEdit(start=start, end=end, replacement=replacement),
                            ),
                        ),
                    )
                )
            return diagnostics

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind != TokenKind.KEYWORD or tok.text.lower() != "end":
                i += 1
                continue

            matched: tuple[tuple[str, ...], str, int] | None = None
            for words, compact in _SPACED_END_TO_COMPACT.items():
                if len(words) < 2:
                    continue
                if i + len(words) > len(tokens):
                    continue
                window = tokens[i : i + len(words)]
                if any(w.kind != TokenKind.KEYWORD for w in window):
                    continue
                window_words = tuple(w.text.lower() for w in window)
                if window_words != words:
                    continue
                matched = (words, compact, len(words))
                break

            if matched is None:
                i += 1
                continue

            _words, compact, width = matched
            end_tok = tokens[i + width - 1]
            replacement = _keyword_case(compact, ctx.cfg.keyword_case)
            start = _token_start(ctx, tok)
            end = _token_end(ctx, end_tok)
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=tok.line,
                    col=tok.col,
                    end_line=end_tok.line,
                    end_col=end_tok.col + len(end_tok.text),
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message=f"Replace {' '.join(matched[0])} with {replacement}",
                        edits=(
                            TextEdit(start=start, end=end, replacement=replacement),
                        ),
                    ),
                )
            )
            i += width
        return diagnostics


class SBL003DeclarationDoubleColonRule:
    """Insert missing :: in declaration statements when safe to do so."""

    rule_id = "SBL003"
    summary = "Declaration is missing '::'."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for logical_line in ctx.logical_lines:
            non_comment = [tok for tok in logical_line if tok.kind != TokenKind.COMMENT]
            if not non_comment:
                continue
            if any(tok.kind == TokenKind.CONTINUATION for tok in non_comment):
                continue
            if len({tok.line for tok in non_comment}) != 1:
                continue
            if any(tok.kind == TokenKind.DOUBLE_COLON for tok in non_comment):
                continue
            decl = _parse_declaration(non_comment)
            if decl is None:
                continue

            canonical = _canonicalise_declaration_tokens(non_comment)
            replacement = _render_tokens(canonical)
            first, last = non_comment[0], non_comment[-1]
            start = _token_start(ctx, first)
            end = _token_end(ctx, last)
            original = ctx.source[start:end]
            if replacement == original:
                continue

            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=first.line,
                    col=first.col,
                    end_line=last.line,
                    end_col=last.col + len(last.text),
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Insert declaration separator '::'",
                        edits=(
                            TextEdit(start=start, end=end, replacement=replacement),
                        ),
                    ),
                )
            )
        return diagnostics


class SBL004SemicolonSplitRule:
    """Split semicolon-separated statements onto separate lines."""

    rule_id = "SBL004"
    summary = "Semicolon-separated statements should be split to separate lines."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for tok in ctx.tokens:
            if tok.kind != TokenKind.SEMICOLON:
                continue
            line_start = ctx.line_starts[tok.line - 1]
            line_end = ctx.source.find("\n", line_start)
            if line_end == -1:
                line_end = len(ctx.source)
            line_text = ctx.source[line_start:line_end]
            indent = re.match(r"[ \t]*", line_text).group(0)
            start = _token_start(ctx, tok)
            end = _token_end(ctx, tok)
            while end < len(ctx.source) and ctx.source[end] in (" ", "\t"):
                end += 1
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=tok.line,
                    col=tok.col,
                    end_line=tok.line,
                    end_col=tok.col + 1,
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Split statement at semicolon",
                        edits=(
                            TextEdit(start=start, end=end, replacement="\n" + indent),
                        ),
                    ),
                )
            )
        return diagnostics


class SBL005TrailingWhitespaceRule:
    """Enforce no trailing spaces and exactly one trailing newline."""

    rule_id = "SBL005"
    summary = "Trailing whitespace or trailing newline style is non-canonical."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for match in re.finditer(r"[ \t]+(?=\n|$)", ctx.source):
            start = match.start()
            end = match.end()
            line, col = _offset_to_line_col(ctx, start)
            end_line, end_col = _offset_to_line_col(ctx, end)
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=line,
                    col=col,
                    end_line=end_line,
                    end_col=end_col,
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Remove trailing whitespace",
                        edits=(TextEdit(start=start, end=end, replacement=""),),
                    ),
                )
            )

        if ctx.source.endswith("\n"):
            stripped = ctx.source.rstrip("\n")
            if len(ctx.source) - len(stripped) > 1:
                start = len(stripped)
                end = len(ctx.source)
                line, col = _offset_to_line_col(ctx, start)
                diagnostics.append(
                    Diagnostic(
                        rule_id=self.rule_id,
                        message=self.summary,
                        line=line,
                        col=col,
                        end_line=line,
                        end_col=col + (end - start),
                        severity=Severity.WARNING,
                        path=ctx.path,
                        fix=Fix(
                            message="Keep a single trailing newline",
                            edits=(TextEdit(start=start, end=end, replacement="\n"),),
                        ),
                    )
                )
        else:
            line, col = _offset_to_line_col(ctx, len(ctx.source))
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=line,
                    col=col,
                    end_line=line,
                    end_col=col,
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Add trailing newline",
                        edits=(
                            TextEdit(
                                start=len(ctx.source),
                                end=len(ctx.source),
                                replacement="\n",
                            ),
                        ),
                    ),
                )
            )

        return diagnostics


class SBL009TabIndentationRule:
    """Disallow tabs in leading indentation for free-form Fortran."""

    rule_id = "SBL009"
    summary = "Tab indentation is non-canonical; use spaces."

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        lines = ctx.source.splitlines(keepends=True)
        offset = 0
        tab_re = re.compile(r"[ \t]*")

        for line_no, line in enumerate(lines, start=1):
            line_body = line[:-1] if line.endswith("\n") else line
            if not line_body:
                offset += len(line)
                continue
            if line_body.lstrip().startswith("!"):
                offset += len(line)
                continue

            indent = tab_re.match(line_body).group(0)
            if "\t" not in indent:
                offset += len(line)
                continue

            start = offset
            end = offset + len(indent)
            replacement = indent.replace("\t", " " * ctx.cfg.indent_width)
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=line_no,
                    col=1,
                    end_line=line_no,
                    end_col=len(indent) + 1,
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Replace tab indentation with spaces",
                        edits=(
                            TextEdit(start=start, end=end, replacement=replacement),
                        ),
                    ),
                )
            )
            offset += len(line)

        return diagnostics


class SBL010StrayLeadingContinuationRule:
    """Detect continuation lines that start with '&' without a prior continuation."""

    rule_id = "SBL010"
    summary = (
        "Line starts with continuation marker '&' but previous line is not continued."
    )

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        lines = ctx.source.splitlines(keepends=True)
        prev_continues = False
        offset = 0

        for line_no, line in enumerate(lines, start=1):
            line_body = line[:-1] if line.endswith("\n") else line
            stripped = line_body.lstrip()

            if not stripped or stripped.startswith("!"):
                offset += len(line)
                continue

            leading_ws_len = len(line_body) - len(stripped)

            if stripped.startswith("&") and not prev_continues:
                start = offset + leading_ws_len
                end = start + 1
                # Also drop one optional space right after '&' to avoid artifacts.
                while end < offset + len(line_body) and ctx.source[end] == " ":
                    end += 1
                diagnostics.append(
                    Diagnostic(
                        rule_id=self.rule_id,
                        message=self.summary,
                        line=line_no,
                        col=leading_ws_len + 1,
                        end_line=line_no,
                        end_col=leading_ws_len + 2,
                        severity=Severity.WARNING,
                        path=ctx.path,
                        fix=Fix(
                            message="Remove stray leading continuation marker",
                            edits=(TextEdit(start=start, end=end, replacement=""),),
                        ),
                    )
                )

            code_no_comment = line_body.split("!", 1)[0].rstrip()
            prev_continues = code_no_comment.endswith("&")
            offset += len(line)

        return diagnostics


class SBL101MissingImplicitNoneRule:
    """Detect program units that do not contain `implicit none`."""

    rule_id = "SBL101"
    summary = "Program unit is missing 'implicit none'."

    _UNIT_KINDS = {"program", "module", "subroutine", "function"}
    _END_COMPACT = {
        "endprogram": "program",
        "endmodule": "module",
        "endsubroutine": "subroutine",
        "endfunction": "function",
    }

    def _line_keywords(self, line_tokens: list[Token]) -> list[str]:
        return [
            tok.text.lower()
            for tok in line_tokens
            if tok.kind == TokenKind.KEYWORD and tok.text
        ]

    def _find_opener(self, words: list[str]) -> str | None:
        if not words:
            return None
        if words[0] == "end":
            return None
        if words[0] == "module" and len(words) > 1 and words[1] == "procedure":
            return None
        for word in words:
            if word in self._UNIT_KINDS:
                return word
        return None

    def _find_closer(self, words: list[str]) -> str | None:
        if not words:
            return None
        if words[0] == "end":
            if len(words) > 1 and words[1] in self._UNIT_KINDS:
                return words[1]
            return None
        return self._END_COMPACT.get(words[0])

    def _has_implicit_none(self, words: list[str]) -> bool:
        for i in range(len(words) - 1):
            if words[i] == "implicit" and words[i + 1] == "none":
                return True
        return False

    def check(self, ctx: RuleContext) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        lines = ctx.source.splitlines(keepends=True)
        stack: list[dict[str, object]] = []

        for logical_line in ctx.logical_lines:
            non_comment = [tok for tok in logical_line if tok.kind != TokenKind.COMMENT]
            if not non_comment:
                continue
            keywords = self._line_keywords(non_comment)
            if not keywords:
                continue
            line_no = non_comment[0].line

            if stack and self._has_implicit_none(keywords):
                stack[-1]["has_implicit"] = True

            opener = self._find_opener(keywords)
            if opener is not None:
                line_text = lines[line_no - 1].rstrip("\n")
                leading = re.match(r"[ \t]*", line_text).group(0)
                stack.append(
                    {
                        "kind": opener,
                        "line": line_no,
                        "indent": leading + (" " * ctx.cfg.indent_width),
                        "has_implicit": False,
                    }
                )
                continue

            closer = self._find_closer(keywords)
            if closer is None or not stack:
                continue
            if stack[-1]["kind"] != closer:
                continue

            frame = stack.pop()
            if frame["has_implicit"]:
                continue

            start_line = int(frame["line"])
            if start_line < len(ctx.line_starts):
                insert_at = ctx.line_starts[start_line]
                prefix = ""
            else:
                insert_at = len(ctx.source)
                prefix = "\n" if not ctx.source.endswith("\n") else ""
            statement = _keyword_case("implicit none", ctx.cfg.keyword_case)
            replacement = f"{prefix}{frame['indent']}{statement}\n"
            diagnostics.append(
                Diagnostic(
                    rule_id=self.rule_id,
                    message=self.summary,
                    line=start_line,
                    col=1,
                    end_line=start_line,
                    end_col=1,
                    severity=Severity.WARNING,
                    path=ctx.path,
                    fix=Fix(
                        message="Insert implicit none in specification part",
                        edits=(
                            TextEdit(
                                start=insert_at, end=insert_at, replacement=replacement
                            ),
                        ),
                        safety=FixSafety.UNSAFE,
                    ),
                )
            )

        return diagnostics
