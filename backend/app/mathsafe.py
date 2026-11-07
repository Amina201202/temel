"""LLM-in yazdigi riyazi ifadeleri tehlukesiz hesablayir.

eval() ve sympify() istifade etmirik: dersliyin metni prompt-a gedir,
ora yazilan sey (prompt injection) koda cevrile biler. Ona gore ifadeni
ast ile parse edib yalniz icaze verilen node-lari ozumuz hesablayiriq.
"""
import ast
import operator

import re

from sympy import (Basic, Integer, Rational, Symbol, divisor_count, expand, factor, floor, gcd, lcm, nan, oo,
                   sqrt, together, zoo)

MAX_LEN = 200
MAX_POW = 6


class UnsafeExpression(ValueError):
    pass


class Shown(str):
    """Yazilis formasi vacib olan cavab: 6/8 ile 3/4 ferqlidir.
    Rational ozu ixtisar edir, ona gore ixtisar ve qarisiq eded suallari ucun bu lazimdir."""
    is_finite = True


def _whole(x):
    if not getattr(x, "is_integer", False):
        raise ValueError("Frac/Mixed yalniz tam ededlerle isleyir")
    return int(x)


def make_frac(p, q):
    if _whole(q) == 0:
        raise ZeroDivisionError
    return Shown(f"{_whole(p)}/{_whole(q)}")


def make_mixed(w, p, q):
    if _whole(q) == 0:
        raise ZeroDivisionError
    if _whole(p) == 0:
        return Shown(str(_whole(w)))
    return Shown(f"{_whole(w)} {_whole(p)}/{_whole(q)}")


X = Symbol("x")


def disc(a, b, c):
    return b ** 2 - 4 * a * c


def label_roots(values):
    vals = sorted(set(values), key=lambda v: float(v))
    if not vals:
        return Shown("Həqiqi kök yoxdur")
    if len(vals) == 1:
        return Shown(f"x = {format_value(vals[0])}")
    return Shown(", ".join(f"x{'₁₂'[i]} = {format_value(v)}" for i, v in enumerate(vals[:2])))


def make_roots(a, b, c):
    # a*x^2 + b*x + c = 0 tenliyinin heqiqi kokleri, deqiq (sqrt ile)
    if a == 0:
        raise ValueError("a 0 ola bilmez")
    d = disc(a, b, c)
    if d < 0:
        return label_roots([])
    return label_roots([(-b + sqrt(d)) / (2 * a), (-b - sqrt(d)) / (2 * a)])


def make_roots_of(*values):
    # sehv variantlar ucun: kokleri ozun hesabla, men yazim
    real = [v for v in values if getattr(v, "is_real", False)]
    return label_roots(real)


FUNCS = {
    "Rational": lambda p, q: Rational(p, q),
    "gcd": gcd,
    "lcm": lcm,
    "floor": floor,
    "abs": abs,
    "max": max,
    "min": min,
    "ndivisors": divisor_count,
    "Frac": make_frac,
    "Mixed": make_mixed,
    # qarisiq ededin QIYMETI: Mix(2, 1, 3) = 7/3, onunla hesablamaq olur
    "Mix": lambda w, p, q: w + Rational(p, q),
    # 8-9-cu sinif
    "sqrt": sqrt,
    "Disc": disc,
    "Roots": make_roots,
    "RootsOf": make_roots_of,
    "expand": expand,
    "factor": factor,
}

BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

CMP_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


def check_syntax(expr, allowed_names):
    # hesablamadan evvel ifadenin icaze verilen formada oldugunu yoxlayir
    if not isinstance(expr, str) or not expr.strip():
        raise UnsafeExpression("ifadə boşdur")
    if len(expr) > MAX_LEN:
        raise UnsafeExpression("ifadə çox uzundur")
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names and node.id not in FUNCS and node.id != "x":
            raise UnsafeExpression(f"naməlum ad: {node.id}")
        if isinstance(node, ast.Attribute):
            raise UnsafeExpression("atributa giriş qadağandır")
    return tree


def evaluate(expr, env):
    try:
        tree = check_syntax(expr, set(env))
        return _eval(tree.body, env)
    except (UnsafeExpression, ZeroDivisionError):
        raise
    except Exception as e:  # noqa: BLE001
        # SyntaxError, AttributeError, sympy xetalari... hamisini bir tipe ceviririk
        raise UnsafeExpression(f"ifadə hesablanmadı ({type(e).__name__})") from e


def _eval(node, env):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise UnsafeExpression("yalnız tam ədəd sabitlərinə icazə var")
        return Integer(node.value)

    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id == "x":
            return X
        raise UnsafeExpression(f"naməlum dəyişən: {node.id}")

    if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
        left = _eval(node.left, env)
        right = _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and (not right.is_integer or abs(right) > MAX_POW):
            raise UnsafeExpression("üst çox böyükdür")
        return BIN_OPS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval(node.operand, env)
        return -value if isinstance(node.op, ast.USub) else value

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS:
        if node.keywords:
            raise UnsafeExpression("keyword arqumentlərə icazə yoxdur")
        args = [_eval(a, env) for a in node.args]
        return FUNCS[node.func.id](*args)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in CMP_OPS:
                raise UnsafeExpression("bu müqayisəyə icazə yoxdur")
            right = _eval(comp, env)
            if not CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)

    raise UnsafeExpression(f"icazə verilməyən ifadə: {type(node).__name__}")


def is_valid(value):
    if isinstance(value, Shown):
        return True
    if isinstance(value, Basic):
        if value.free_symbols:
            return not value.has(zoo, nan, oo, -oo)
        return bool(value.is_finite)
    return False


def pretty_expr(value):
    # sympy yazisini sagird ucun: x**2 -> x², 2*x -> 2x, sqrt(3) -> √3
    t = str(value)
    t = re.sub(r"sqrt\((\d+)\)", r"√\1", t)
    t = t.replace("**2", "²").replace("**3", "³")
    t = re.sub(r"(\d)\*([x√(])", r"\1\2", t)
    t = t.replace(")*(", ")(").replace("*", "·")
    # irrasional kesrde "/" etrafinda bosluq: ekranda √(3/2) kimi gorunmesin
    t = re.sub(r"(?<=[√\w)])/(?=\d)", " / ", t) if "√" in t or "x" in t else t
    return t.replace("-", "−")


def format_value(value, fmt="fraction"):
    # Rational-i sagird ucun yaziya cevirir: 11/12, 3, 2 1/3
    if isinstance(value, Shown):
        return str(value)
    if isinstance(value, Basic) and (value.free_symbols or not value.is_rational):
        # (1 + √5)/2 bir kesr kimi qalsin, iki parcaya bolunmesin
        return pretty_expr(value if value.free_symbols else together(value))
    value = Rational(value)
    if value.q == 1:
        return str(value.p).replace("-", "−")
    if fmt == "mixed" and abs(value) > 1:
        whole = int(value.p / value.q)
        rest = abs(value - whole)
        return f"{whole} {rest.p}/{rest.q}".replace("-", "−")
    return f"{value.p}/{value.q}".replace("-", "−")
