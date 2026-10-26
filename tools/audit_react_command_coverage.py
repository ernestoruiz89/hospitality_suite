"""List Suite commands without a literal reference in the React source.

This is a discovery aid: dynamic command names and intentionally internal
commands need a manual review before declaring a screen absent.
"""

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    api = ast.parse((ROOT / "hospitality_suite/api.py").read_text(
        encoding="utf-8"))
    command_map = next(node.value for node in api.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "COMMANDS"
            for target in node.targets))
    names = sorted(key.value for key in command_map.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str))
    sources = {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8")
        for path in (ROOT / "frontend/src").rglob("*")
        if path.suffix in (".ts", ".tsx")}
    unused = [name for name in names if not any(
        f'"{name}"' in source or f"'{name}'" in source
        for source in sources.values())]
    print(json.dumps({"commands": len(names),
        "without_literal_react_reference": unused,
        "scope": "Static literal references only; review dynamic and internal commands"},
        indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
