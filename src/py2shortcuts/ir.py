"""Small, target-neutral IR used between the Python frontend and backends."""

from __future__ import annotations

from dataclasses import dataclass


type Scalar = str | int | float | bool | None


class Expr:
    pass


class Stmt:
    pass


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    value: Scalar


@dataclass(frozen=True, slots=True)
class Var(Expr):
    name: str


@dataclass(frozen=True, slots=True)
class Symbol(Expr):
    """Compile-time symbol imported from a facade package."""

    name: str


@dataclass(frozen=True, slots=True)
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class Unary(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True, slots=True)
class Compare(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class BoolExpr(Expr):
    op: str
    values: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class Call(Expr):
    target: str
    args: tuple[Expr, ...]
    kwargs: tuple[tuple[str, Expr], ...] = ()

    def keyword(self, name: str) -> Expr | None:
        for key, value in self.kwargs:
            if key == name:
                return value
        return None


@dataclass(frozen=True, slots=True)
class ListExpr(Expr):
    items: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class DictExpr(Expr):
    items: tuple[tuple[Expr, Expr], ...]


@dataclass(frozen=True, slots=True)
class Subscript(Expr):
    value: Expr
    key: Expr


@dataclass(frozen=True, slots=True)
class FormatString(Expr):
    parts: tuple[str | Expr, ...]


@dataclass(frozen=True, slots=True)
class Assign(Stmt):
    name: str
    value: Expr


@dataclass(frozen=True, slots=True)
class ExprStmt(Stmt):
    value: Expr


@dataclass(frozen=True, slots=True)
class IfStmt(Stmt):
    condition: Expr
    body: tuple[Stmt, ...]
    orelse: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class ForEachStmt(Stmt):
    target: str
    iterable: Expr
    body: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class ForRangeStmt(Stmt):
    target: str
    start: Expr
    stop: Expr
    step: Expr
    body: tuple[Stmt, ...]


@dataclass(frozen=True, slots=True)
class Module:
    body: tuple[Stmt, ...]
