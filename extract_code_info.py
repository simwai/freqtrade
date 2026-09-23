"""Reconstruct server.py from server.cpython-310.pyc

This script uses marshal to load the bytecode and dis to extract
function signatures, then attempts to reconstruct the source.
"""

import marshal
import dis
import types
import sys


def get_code_info(code, depth=0):
    """Extract information from a code object."""
    info = {
        "name": code.co_name,
        "varnames": code.co_varnames,
        "argcount": code.co_argcount,
        "args": code.co_varnames[: code.co_argcount],
        "locals": code.co_varnames[code.co_argcount : code.co_argcount + code.co_nlocals],
        "freevars": code.co_freevars,
        "cellvars": code.co_cellvars,
        "consts": [],
        "instructions": list(dis.get_instructions(code)),
    }
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            info["consts"].append(("CODE", get_code_info(const, depth + 1)))
        else:
            info["consts"].append(("VAL", const))
    return info


def format_const(val):
    if isinstance(val, str):
        if "\n" in val:
            return repr(val)
        return f'"{val}"'
    elif isinstance(val, bytes):
        return f'b"{val.decode("utf-8", errors="replace")}"'
    elif val is None:
        return "None"
    elif val is True:
        return "True"
    elif val is False:
        return "False"
    elif isinstance(val, (int, float)):
        return repr(val)
    elif isinstance(val, tuple):
        return f"({', '.join(format_const(v) for v in val)})"
    elif isinstance(val, list):
        return f"[{', '.join(format_const(v) for v in val)}]"
    elif isinstance(val, dict):
        items = ", ".join(f"{format_const(k)}: {format_const(v)}" for k, v in val.items())
        return f"{{{items}}}"
    elif isinstance(val, set):
        items = ", ".join(format_const(v) for v in val)
        return f"{{{items}}}"
    return repr(val)


with open("user_data/scripts/__pycache__/server.cpython-310.pyc", "rb") as f:
    f.read(16)
    code = marshal.load(f)

info = get_code_info(code)

# Write a summary
with open("user_data/scripts/server_code_info.txt", "w") as f:
    f.write(f"Module: {info['name']}\n")
    f.write(f"Args: {info['args']}\n")
    f.write(f"Locals: {info['locals']}\n")
    f.write(f"Freevars: {info['freevars']}\n")
    f.write(f"Cellvars: {info['cellvars']}\n")
    f.write(f"\nConstants ({len(info['consts'])}):\n")
    for i, (typ, val) in enumerate(info["consts"]):
        if typ == "CODE":
            f.write(f"  [{i}] CODE: {val['name']} args={val['args']}\n")
            for j, (typ2, val2) in enumerate(val["consts"]):
                if typ2 == "CODE":
                    f.write(f"    [{i}.{j}] CODE: {val2['name']}\n")
                else:
                    f.write(f"    [{i}.{j}] {format_const(val2)[:100]}\n")
        else:
            f.write(f"  [{i}] {format_const(val)[:100]}\n")

print("Code info written to server_code_info.txt")
print(f"Total constants: {len(info['consts'])}")
