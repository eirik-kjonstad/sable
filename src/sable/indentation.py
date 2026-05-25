"""Indentation tracking for formatted logical lines."""

from __future__ import annotations

from . import analysis as _analysis
from .tokens import Token, TokenKind

# Keywords that close an indentation level (decrease before rendering)
_INDENT_CLOSE: frozenset[str] = frozenset(
    {
        "end",
        "endif",
        "enddo",
        "endfunction",
        "endsubroutine",
        "endmodule",
        "endprogram",
        "endwhere",
        "endselect",
        "endinterface",
        "endtype",
        "endassociate",
        "endblock",
        "endcritical",
        "endteam",
        "endenum",
        "end if",
        "end do",
        "end function",
        "end subroutine",
        "end module",
        "end program",
        "end where",
        "end select",
        "end interface",
        "end type",
        "end associate",
        "end block",
        "end critical",
        "end team",
        "end enum",
        "else",
        "elseif",
        "case",
        "contains",
    }
)


class IndentTracker:
    """Track indentation level as we walk logical lines."""

    def __init__(self, indent_width: int) -> None:
        self.level = 0
        self.width = indent_width
        # Per active SELECT construct, track whether a selector branch body is open.
        self._select_branch_open: list[bool] = []

    def indent(self) -> str:
        return " " * (self.level * self.width)

    def open(self) -> None:
        self.level += 1

    def close(self) -> None:
        self.level = max(0, self.level - 1)

    def process_line(self, line_tokens: list[Token]) -> tuple[str, bool]:
        """Return (indentation_string, did_close) for a logical line."""
        if not line_tokens:
            return self.indent(), False

        non_comment = _analysis.core_tokens(line_tokens)
        first = _analysis.first_keyword(line_tokens)
        is_select_branch = _analysis.is_select_branch(non_comment)
        is_end_select = _analysis.is_end_select(non_comment)
        did_close = False

        # Selector guards (`case`, `type is`, `class ...`, `rank ...`) close only
        # the previous selector body, not the select construct itself.
        if is_select_branch:
            if self._select_branch_open and self._select_branch_open[-1]:
                self.close()
                did_close = True
                self._select_branch_open[-1] = False
        else:
            # If we are ending a SELECT while inside the last selector body, close
            # that body before applying the normal `end select` close.
            if (
                is_end_select
                and self._select_branch_open
                and self._select_branch_open[-1]
            ):
                self.close()
                did_close = True
                self._select_branch_open[-1] = False

            closes = first in _INDENT_CLOSE or _analysis.is_select_guard(non_comment)
            if not closes and _analysis.is_labelled_continue(line_tokens):
                # Legacy labelled-do termination: `10 continue` closes one DO level.
                closes = True
            if closes:
                self.close()
                did_close = True

        ind = self.indent()

        last = line_tokens[-1].text.lower() if line_tokens else ""
        if non_comment:
            last_tok = non_comment[-1]
            last = last_tok.text.lower()
            # `end ...` constructs (both compact `enddo` and spaced `end do`)
            # are pure closers. The trailing keyword (`do`, `associate`, ...)
            # names what is being ended, not a new block opener. Other closing
            # keywords (`else`, `elseif`, `case`, `contains`) legitimately
            # re-open via their last token (e.g. `then`).
            can_open_via_last = not (did_close and first.startswith("end"))
            # A trailing opener is only needed for `if (...) then` constructs.
            opens_via_last = (
                can_open_via_last
                and last_tok.kind == TokenKind.KEYWORD
                and last == "then"
            )
            opened = opens_via_last or _analysis.is_block_opener(first, non_comment)
            if opened:
                self.open()
                if first == "select":
                    self._select_branch_open.append(False)
                elif is_select_branch and self._select_branch_open:
                    self._select_branch_open[-1] = True

            if is_end_select and self._select_branch_open:
                self._select_branch_open.pop()

        return ind, did_close
