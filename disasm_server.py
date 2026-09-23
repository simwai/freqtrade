import marshal
import dis
import types

with open("user_data/scripts/__pycache__/server.cpython-310.pyc", "rb") as f:
    f.read(16)
    code = marshal.load(f)


def disasm_to_str(code, indent=0):
    lines = []
    prefix = "  " * indent
    lines.append(f"{prefix}=== {code.co_name} ===")
    lines.append(f"{prefix}Args: {code.co_varnames[: code.co_argcount]}")
    lines.append(
        f"{prefix}Locals: {code.co_varnames[code.co_argcount : code.co_argcount + code.co_nlocals]}"
    )
    lines.append(f"{prefix}Constants: {len(code.co_consts)}")

    for instr in dis.get_instructions(code):
        argval = instr.argval if instr.argval is not None else ""
        lines.append(f"{prefix}  {instr.opname} {argval}")

    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            lines.append("")
            lines.extend(disasm_to_str(const, indent + 1))

    return lines


output = disasm_to_str(code)
with open("user_data/scripts/server_disasm.txt", "w") as f:
    f.write("\n".join(output))
print(f"Total lines: {len(output)}")
