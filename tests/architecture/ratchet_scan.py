"""Count the stocks the architecture ratchets freeze.

``os.environ`` and a ``${NAME}`` locator regex stay where they already are.
A new file fails the ratchet. String-coded raises (``raise Error("code:...")``)
and ``dict[str, Any]`` counts may fall and may not rise.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_ROOTS = ("src", "plugins", "services", "scripts")
_ENVIRON = re.compile(r"\bos\.environ\b")
_DICT_ANY = re.compile(r"\b(?:dict|Dict)\[str,\s*Any\]")
_CODED = re.compile(r"^[a-z][a-z0-9_]*:")
_RE_FUNCS = frozenset(
    {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}
)
_EXECUTOR_ROOTS = (REPO / "src" / "ageval" / "plugins", REPO / "plugins")


def _py_files() -> list[Path]:
    found: list[Path] = []
    for name in _ROOTS:
        base = REPO / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            found.append(path)
    return found


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _module_key(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "src" and len(parts) > 2 and parts[1] == "ageval":
        return f"src/ageval/{parts[2]}"
    if parts[0] == "src" and len(parts) > 1 and parts[1] == "ageval_sdk":
        return "src/ageval_sdk"
    if parts[0] in {"plugins", "services"} and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def count_environ() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in _py_files():
        n = len(_ENVIRON.findall(path.read_text(encoding="utf-8")))
        if n:
            out[_rel(path)] = n
    return out


def count_dict_any() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in _py_files():
        n = len(_DICT_ANY.findall(path.read_text(encoding="utf-8")))
        if not n:
            continue
        key = _module_key(_rel(path))
        out[key] = out.get(key, 0) + n
    return out


def _string_bits(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        if isinstance(node.value, bytes):
            return [node.value.decode("utf-8", errors="replace")]
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        bits: list[str] = []
        for value in node.values:
            bits.extend(_string_bits(value))
        return bits
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_bits(node.left) + _string_bits(node.right)
    return []


def _is_re_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _RE_FUNCS
        and isinstance(func.value, ast.Name)
        and func.value.id == "re"
    )


def _locator_regex(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not _is_re_call(node):
        return False
    for arg in node.args:
        for bit in _string_bits(arg):
            if "${" in bit or r"\$\{" in bit:
                return True
    return False


def _coded_raise(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
        return False
    if not node.exc.args:
        return False
    prefix = ""
    first = node.exc.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        prefix = first.value
    elif isinstance(first, ast.JoinedStr) and first.values:
        head = first.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            prefix = head.value
    return _CODED.match(prefix) is not None


def _ast_counts() -> tuple[dict[str, int], dict[str, int]]:
    locator: dict[str, int] = {}
    coded: dict[str, int] = {}
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        loc_n = 0
        code_n = 0
        for node in ast.walk(tree):
            if _locator_regex(node):
                loc_n += 1
            if _coded_raise(node):
                code_n += 1
        rel = _rel(path)
        if loc_n:
            locator[rel] = loc_n
        if code_n:
            coded[rel] = code_n
    return locator, coded


def count_locator_regex() -> dict[str, int]:
    locator, _coded = _ast_counts()
    return locator


def count_coded_raises() -> dict[str, int]:
    _locator, coded = _ast_counts()
    return coded


def _decorated_executor(node: ast.ClassDef) -> bool:
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Name) and target.id == "executor_plugin":
            return True
    return False


def _subclasses_base_executor(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseExecutor":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseExecutor":
            return True
    return False


def executor_plugin_gaps() -> list[str]:
    """``@executor_plugin`` classes that do not subclass ``BaseExecutor``."""
    gaps: list[str] = []
    for root in _EXECUTOR_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or not _decorated_executor(node):
                    continue
                if not _subclasses_base_executor(node):
                    gaps.append(f"{_rel(path)}:{node.name}")
    return gaps


def snapshot() -> dict[str, dict[str, int]]:
    locator, coded = _ast_counts()
    return {
        "os_environ": count_environ(),
        "locator_regex": locator,
        "coded_raise": coded,
        "dict_any": count_dict_any(),
    }
