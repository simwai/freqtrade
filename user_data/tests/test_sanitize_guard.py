import ast
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "user_data" / "scripts"
SRC = SCRIPTS / "api_server.py"
sys.path.insert(0, str(SCRIPTS))


def _linenos():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    guard = None
    san = None
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            left = n.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                guard = n.lineno
        if isinstance(n, ast.FunctionDef) and n.name == "sanitize":
            san = n.lineno
    assert guard is not None, "no __main__ guard found"
    assert san is not None, "no sanitize def found"
    return san, guard


def test_sanitize_defined_before_main_guard():
    san, guard = _linenos()
    assert san < guard, (
        "sanitize must be defined before the __main__ guard so script-mode servers can use it"
    )


def test_sanitize_roundtrip_inf_nan():
    import api_server as api

    out = api.sanitize({"a": float("inf"), "b": [1.0, float("nan")], "c": (float("-inf"), "x")})
    assert out == {"a": None, "b": [1.0, None], "c": (None, "x")}
    import json as _j

    _j.dumps(out, allow_nan=False)
