"""
ARIA - Calculator Tool
=======================

Safely evaluate mathematical expressions using a restricted execution environment.
No access to builtins, os, sys, or any dangerous modules — only math functions.
"""

import ast
import logging
import math
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.calculator")

# Whitelisted math functions and constants available in expressions
SAFE_GLOBALS = {
    "__builtins__": {},  # No builtins — security critical
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "pi": math.pi,
    "e": math.e,
    "pow": pow,
    "floor": math.floor,
    "ceil": math.ceil,
}

# AST node types that are allowed in expressions
ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.USub, ast.UAdd,
    ast.Tuple, ast.List,
)


def _validate_ast(node: ast.AST) -> None:
    """Walk the AST and reject any disallowed node types."""
    if not isinstance(node, ALLOWED_NODES):
        raise ValueError(f"Disallowed expression element: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _validate_ast(child)


class CalculatorTool(ToolBase):
    """Safely evaluate mathematical expressions."""

    name = "calculator"
    description = (
        "Evaluate a mathematical expression safely. "
        "Supports: +, -, *, /, //, **, %, sqrt, sin, cos, tan, log, "
        "pi, e, abs, round, min, max, pow, floor, ceil."
    )
    parameters = [
        ToolParam(
            name="expression",
            type="string",
            description="Mathematical expression to evaluate (e.g. 'sqrt(2) * pi')",
            required=True,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        expression = kwargs["expression"].strip()
        if not expression:
            return ToolResult(success=False, error="Expression is empty")

        try:
            tree = compile(expression, "<calc>", "eval", flags=ast.PyCF_ONLY_AST)
            _validate_ast(tree)
        except SyntaxError as e:
            return ToolResult(success=False, error=f"Invalid syntax: {e}")
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        try:
            code = compile(tree, "<calc>", "eval")
            result = eval(code, SAFE_GLOBALS)
        except ZeroDivisionError:
            return ToolResult(success=False, error="Division by zero")
        except Exception as e:
            logger.warning(f"Calculator eval error: {e}")
            return ToolResult(success=False, error=f"Evaluation error: {e}")

        return ToolResult(
            success=True,
            output=str(result),
            data={"result": result, "expression": expression},
        )
