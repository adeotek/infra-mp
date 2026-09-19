"""Calculated view columns: text concatenation and arithmetic formulas.

The view config carries a ``calculated`` list; each entry is either

    {"label": "Location", "kind": "concat", "parts": ["floor", "room"], "separator": " / "}
    {"label": "Yearly", "kind": "formula", "expr": "round({price} * 12, 2)"}

``parts`` and the ``{…}`` references name *resolved view columns* by their key:
a base attribute's slug (``price``) or a related column's key
(``rel:up:rack:3:first→capacity``).

Formulas support the four operations with the usual precedence, parentheses,
unary minus and ``round(value[, digits])``. Everything is ``Decimal`` end to
end; a missing or non-numeric input, or a division by zero, evaluates to
``None`` — the grid then renders the em dash instead of a wrong number.

Expressions are parsed into a small AST and evaluated by walking it. There is
deliberately no ``eval``/``exec`` anywhere near user input.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.services.aggregates import to_decimal

# Kinds of calculated column a view config may declare.
CALC_KINDS = ("concat", "formula")

MAX_EXPRESSION_LENGTH = 200
MAX_DEPTH = 16
MAX_ROUND_DIGITS = 12

# AST node tuples: ("num", Decimal) | ("ref", key) | ("neg", node)
#                  | ("bin", op, left, right) | ("round", node, digits | None)
Node = tuple

_TOKEN_PUNCTUATION = {"(": "lparen", ")": "rparen", ",": "comma"}


class FormulaError(ValueError):
    """Raised for a formula that cannot be parsed or references unknown columns."""


def parse_formula(expr: str) -> Node:
    """Parse a formula into an AST; raises :class:`FormulaError` when invalid."""
    expr = (expr or "").strip()
    if not expr:
        raise FormulaError("The formula is empty.")
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise FormulaError(f"The formula is longer than {MAX_EXPRESSION_LENGTH} characters.")
    return _Parser(_tokenize(expr)).parse_expr_top()


def formula_references(node: Node) -> set[str]:
    """Every column key the formula reads."""
    kind = node[0]
    if kind == "ref":
        return {node[1]}
    if kind == "num":
        return set()
    if kind in ("neg",):
        return formula_references(node[1])
    if kind == "round":
        return formula_references(node[1])
    if kind == "bin":
        return formula_references(node[2]) | formula_references(node[3])
    return set()


def evaluate_formula(node: Node, values: dict[str, Any]) -> Decimal | None:
    """Evaluate the AST against ``values`` (key -> stored value).

    ``None`` propagates: a referenced column that is empty, non-numeric (text
    values, booleans) or a division by zero yields ``None``.
    """
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        return to_decimal(values.get(node[1]))
    if kind == "neg":
        inner = evaluate_formula(node[1], values)
        return None if inner is None else -inner
    if kind == "round":
        inner = evaluate_formula(node[1], values)
        if inner is None:
            return None
        digits = node[2] or 0
        try:
            return inner.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        except InvalidOperation:  # pragma: no cover - quantize overflow
            return None

    left = evaluate_formula(node[2], values)
    right = evaluate_formula(node[3], values)
    if left is None or right is None:
        return None
    op = node[1]
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return None if right == 0 else left / right
    return None  # pragma: no cover - parser only emits the operators above


# --------------------------------------------------------------------------- #
# Tokenizer / parser
# --------------------------------------------------------------------------- #


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(expr)
    while index < length:
        char = expr[index]
        if char.isspace():
            index += 1
            continue
        if char == "{":
            end = expr.find("}", index + 1)
            if end == -1:
                raise FormulaError("Unbalanced '{' — close the column reference.")
            name = expr[index + 1 : end].strip()
            if not name:
                raise FormulaError("Empty column reference '{}'.")
            tokens.append(("ref", name))
            index = end + 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and expr[index + 1].isdigit()):
            end = index
            seen_dot = False
            while end < length and (expr[end].isdigit() or (expr[end] == "." and not seen_dot)):
                if expr[end] == ".":
                    seen_dot = True
                end += 1
            tokens.append(("num", expr[index:end]))
            index = end
            continue
        if char in "+-*/,":
            tokens.append(("op" if char in "+-*/" else _TOKEN_PUNCTUATION[char], char))
            index += 1
            continue
        if char in "()":
            tokens.append((_TOKEN_PUNCTUATION[char], char))
            index += 1
            continue
        if char.isalpha() or char == "_":
            end = index
            while end < length and (expr[end].isalnum() or expr[end] == "_"):
                end += 1
            tokens.append(("name", expr[index:end]))
            index = end
            continue
        raise FormulaError(f"Unexpected character {char!r} in the formula.")
    return tokens


class _Parser:
    """Recursive-descent parser: + - (lowest) → * / → unary → primary."""

    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str | None, str | None]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def _next(self) -> tuple[str | None, str | None]:
        token = self._peek()
        self.pos += 1
        return token

    def parse_expr_top(self, depth: int = 0) -> Node:
        node = self._parse_expr(depth)
        if self.pos != len(self.tokens):
            raise FormulaError("Unexpected trailing input in the formula.")
        return node

    def _parse_expr(self, depth: int) -> Node:
        node = self._parse_term(depth)
        while True:
            kind, value = self._peek()
            if kind == "op" and value in ("+", "-"):
                self._next()
                node = ("bin", value, node, self._parse_term(depth))
            else:
                return node

    def _parse_term(self, depth: int) -> Node:
        node = self._parse_unary(depth)
        while True:
            kind, value = self._peek()
            if kind == "op" and value in ("*", "/"):
                self._next()
                node = ("bin", value, node, self._parse_unary(depth))
            else:
                return node

    def _parse_unary(self, depth: int) -> Node:
        kind, value = self._peek()
        if kind == "op" and value in ("+", "-"):
            self._next()
            operand = self._parse_unary(depth)
            return operand if value == "+" else ("neg", operand)
        return self._parse_primary(depth)

    def _parse_primary(self, depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise FormulaError("The formula is nested too deeply.")
        kind, value = self._next()
        if kind == "num":
            try:
                return ("num", Decimal(str(value)))
            except InvalidOperation as exc:  # pragma: no cover - tokenizer guards this
                raise FormulaError(f"Invalid number {value!r}.") from exc
        if kind == "ref":
            return ("ref", str(value))
        if kind == "lparen":
            node = self._parse_expr(depth + 1)
            if self._next()[0] != "rparen":
                raise FormulaError("Missing a closing parenthesis in the formula.")
            return node
        if kind == "name":
            if str(value).lower() != "round":
                raise FormulaError(f"Unknown function {value!r}; only round() is supported.")
            if self._next()[0] != "lparen":
                raise FormulaError("round() needs parentheses, e.g. round({price} * 2, 2).")
            inner = self._parse_expr(depth + 1)
            digits: int | None = None
            if self._peek()[0] == "comma":
                self._next()
                digits_kind, digits_token = self._next()
                if digits_kind != "num" or "." in str(digits_token):
                    raise FormulaError("round() digits must be a whole number, e.g. round({x}, 2).")
                digits = int(str(digits_token))
                if not 0 <= digits <= MAX_ROUND_DIGITS:
                    raise FormulaError(f"round() digits must be between 0 and {MAX_ROUND_DIGITS}.")
            if self._next()[0] != "rparen":
                raise FormulaError("round() is missing its closing parenthesis.")
            return ("round", inner, digits)
        if kind is None:
            raise FormulaError("The formula ends unexpectedly.")
        raise FormulaError(f"Unexpected {value!r} in the formula.")
