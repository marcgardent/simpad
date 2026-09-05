import ast
import sys
from pathlib import Path


def get_full_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        parent = get_full_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    elif isinstance(node, ast.Constant):
        return str(node.value)
    return ""


def is_optional_node(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Subscript):
        base = get_full_name(node.value)
        if base in {"Optional", "typing.Optional"}:
            return True
        if base in {"Union", "typing.Union"}:
            slice_elts = []
            if isinstance(node.slice, ast.Tuple):
                slice_elts = node.slice.elts
            elif isinstance(node.slice, ast.Index) and isinstance(node.slice.value, ast.Tuple):
                slice_elts = node.slice.value.elts
            for elt in slice_elts:
                if isinstance(elt, ast.Constant) and elt.value is None:
                    return True
                if get_full_name(elt) in {"None", "NoneType", "types.NoneType"}:
                    return True
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        if isinstance(node.right, ast.Constant) and node.right.value is None:
            return True
        if isinstance(node.left, ast.Constant) and node.left.value is None:
            return True
        return is_optional_node(node.left) or is_optional_node(node.right)
    return False


def find_quoted_types(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    results = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        val = node.value.strip()
        if val and (val.isidentifier() or any(c in val for c in ("[", "]", ",", "|", " "))):
            results.append(val)
    elif isinstance(node, ast.Subscript):
        results.extend(find_quoted_types(node.value))
        if isinstance(node.slice, ast.Tuple):
            for elt in node.slice.elts:
                results.extend(find_quoted_types(elt))
        elif isinstance(node.slice, ast.Index):
            results.extend(find_quoted_types(node.slice.value))
        else:
            results.extend(find_quoted_types(node.slice))
    elif isinstance(node, ast.BinOp):
        results.extend(find_quoted_types(node.left))
        results.extend(find_quoted_types(node.right))
    return results


class FullOOPLintVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.issues: list[tuple[int, int, str]] = []
        self.current_class: ast.ClassDef | None = None
        self.current_method: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        self.method_uses_self = False

    def _is_inside_factory(self) -> bool:
        stem = Path(self.filename).stem.lower()
        if "factory" in stem:
            return True
        if self.current_class and "factory" in self.current_class.name.lower():
            return True
        if self.current_method:
            m_name = self.current_method.name.lower()
            if m_name.startswith(("factory", "create_", "build_", "make_")) or m_name in {"factory", "create", "build"}:
                return True
        return False

    # --- CALLS: getattr(), hasattr(), setattr(), isinstance() ---
    def visit_Call(self, node: ast.Call):
        func_name = get_full_name(node.func)
        if func_name == "getattr":
            self.issues.append((
                node.lineno, node.col_offset,
                "Call to `getattr()` — dynamic introspection forbidden, remove without ambiguity (breaks interface contracts, static typing, and encapsulation)."
            ))
        elif func_name in {"hasattr", "setattr"}:
            self.issues.append((
                node.lineno, node.col_offset,
                f"Call to `{func_name}()` — dynamic introspection/mutation forbidden (breaks polymorphism and encapsulation)."
            ))
        elif func_name == "isinstance":
            if not self._is_inside_factory():
                self.issues.append((
                    node.lineno, node.col_offset,
                    "Call to `isinstance()` outside Factory — only acceptable inside a Factory. In the rest of the code, use polymorphism or create an abstraction."
                ))
        self.generic_visit(node)

    # --- GENERIC DICTIONARIES: Dict[str, Any] / dict[str, Any] / Dict[str, object] ---
    def visit_Subscript(self, node: ast.Subscript):
        base_name = get_full_name(node.value)
        if base_name in {"dict", "Dict", "typing.Dict"}:
            slice_node = node.slice
            elts = []
            if isinstance(slice_node, ast.Tuple):
                elts = slice_node.elts
            elif isinstance(slice_node, ast.Index) and isinstance(slice_node.value, ast.Tuple):
                elts = slice_node.value.elts

            if len(elts) == 2:
                key_type = get_full_name(elts[0])
                val_type = get_full_name(elts[1])
                if key_type == "str" and val_type in {"Any", "typing.Any", "object"}:
                    self.issues.append((
                        node.lineno, node.col_offset,
                        f"Use of `{base_name}[str, {val_type}]` — primitive obsession: type explicitly and do not use a generic type. If an abstraction is needed, create a dedicated type/class."
                    ))
                    return  # Avoid triggering alert on inner Any

        self.generic_visit(node)

    # --- ANY: Any / typing.Any ---
    def visit_Name(self, node: ast.Name):
        if node.id == "Any":
            self.issues.append((
                node.lineno, node.col_offset,
                "Use of `Any` — type explicitly and do not use generic types. If an abstraction is needed, create a dedicated type."
            ))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # typing.Any
        if get_full_name(node) == "typing.Any":
            self.issues.append((
                node.lineno, node.col_offset,
                "Use of `typing.Any` — type explicitly and do not use generic types. If an abstraction is needed, create a dedicated type."
            ))
            return

        # Detection of self usage
        if get_full_name(node.value) == "self":
            self.method_uses_self = True

        # Direct access to __dict__
        if node.attr == "__dict__":
            self.issues.append((
                node.lineno, node.col_offset,
                "Direct access to `__dict__` — breaks the object model and encapsulation."
            ))

        # Law of Demeter (Train Wreck): a.b.c.d
        depth = 0
        curr = node
        while isinstance(curr, ast.Attribute):
            depth += 1
            curr = curr.value
        if depth >= 3:
            self.issues.append((
                node.lineno, node.col_offset,
                f"Law of Demeter violated (depth {depth}) — excessive coupling between structures."
            ))

        self.generic_visit(node)

    # --- GOD CLASS & CLASS STRUCTURES ---
    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class = self.current_class
        self.current_class = node

        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(methods) > 20:
            self.issues.append((
                node.lineno, node.col_offset,
                f"God Class: `{node.name}` exposes {len(methods)} methods (recommended threshold: <= 20)."
            ))

        self.generic_visit(node)
        self.current_class = prev_class

    # --- VARIABLE ANNOTATIONS WITH QUOTED TYPES ---
    def visit_AnnAssign(self, node: ast.AnnAssign):
        quoted = find_quoted_types(node.annotation)
        for q_type in quoted:
            if self.current_class and q_type == self.current_class.name:
                self.issues.append((
                    node.lineno, node.col_offset,
                    f"Attribute annotated with quoted type `\"{q_type}\"` — obsolete forward reference: use `Self` (from typing import Self) instead of quoted class name."
                ))
            else:
                self.issues.append((
                    node.lineno, node.col_offset,
                    f"Attribute annotated with quoted type `\"{q_type}\"` — obsolete forward reference: use `from __future__ import annotations` and unquoted types."
                ))
        self.generic_visit(node)

    # --- FUNCTIONS AND METHODS ---
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._check_function_or_method(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._check_function_or_method(node)

    def _check_function_or_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # 1. Verification of fake dict backdoors: __getitem__, get(), to_dict()
        if self.current_class and node.name in {"__getitem__", "get", "to_dict"}:
            base_names = [get_full_name(b) for b in self.current_class.bases]
            is_collection = any(
                b in {"dict", "Dict", "Mapping", "MutableMapping", "typing.Mapping", "typing.MutableMapping"}
                for b in base_names
            )
            if not is_collection:
                self.issues.append((
                    node.lineno, node.col_offset,
                    f"Method `{node.name}()` in `{self.current_class.name}` — fake dict backdoor / primitive obsession: a domain object must not behave like a dictionary nor expose its internal state via `get()` or `to_dict()`."
                ))

        # 2. Verification of Option(al) arguments
        all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        for arg in all_args:
            if arg.arg in {"self", "cls", "parent"}:
                continue
            if is_optional_node(arg.annotation):
                self.issues.append((
                    arg.lineno, arg.col_offset,
                    f"Argument `{arg.arg}` typed as Option(al) in `{node.name}()` — anti-pattern: either eliminate the call when data is unavailable, or split into two methods (one with data, one without)."
                ))
            # Quoted type in argument
            quoted_arg_types = find_quoted_types(arg.annotation)
            for q_type in quoted_arg_types:
                if self.current_class and q_type == self.current_class.name:
                    self.issues.append((
                        arg.lineno, arg.col_offset,
                        f"Argument `{arg.arg}` annotated with `\"{q_type}\"` — obsolete forward reference: use `Self` (from typing import Self) instead of a quoted forward reference."
                    ))
                else:
                    self.issues.append((
                        arg.lineno, arg.col_offset,
                        f"Argument `{arg.arg}` annotated with `\"{q_type}\"` — obsolete forward reference: use `from __future__ import annotations` and unquoted types."
                    ))

        # 3. Verification of quoted return types (e.g.: def get_instance(cls) -> "TelemetryStateStore")
        if node.returns:
            quoted_ret_types = find_quoted_types(node.returns)
            for q_type in quoted_ret_types:
                if self.current_class and q_type == self.current_class.name:
                    self.issues.append((
                        node.lineno, node.col_offset,
                        f"Return type `\"{q_type}\"` in `{node.name}()` — obsolete forward reference: use `Self` (from typing import Self) instead of quoted class name."
                    ))
                else:
                    self.issues.append((
                        node.lineno, node.col_offset,
                        f"Return type annotated as string `\"{q_type}\"` in `{node.name}()` — obsolete forward reference: use `from __future__ import annotations` and unquoted types."
                    ))

        # 4. Class methods: Feature Envy, @staticmethod, etc.
        if not self.current_class:
            self.generic_visit(node)
            return

        prev_method = self.current_method
        prev_uses_self = self.method_uses_self
        self.current_method = node
        self.method_uses_self = False

        decorators = [get_full_name(d) for d in node.decorator_list]

        if "staticmethod" in decorators:
            self.issues.append((
                node.lineno, node.col_offset,
                f"`@{node.name}` is a `@staticmethod` — pure procedure artificially isolated in a class."
            ))

        self.generic_visit(node)

        # Instance method ignoring self (Feature Envy / disguised function)
        args = [arg.arg for arg in node.args.args]
        is_instance_method = args and args[0] == "self"
        exempt_decorators = {"staticmethod", "classmethod", "property", "abstractmethod"}
        if is_instance_method and not self.method_uses_self and not any(d in exempt_decorators for d in decorators):
            if not (len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Expr))):
                self.issues.append((
                    node.lineno, node.col_offset,
                    f"Method `{node.name}` never uses `self` — logic belongs outside the class."
                ))

        self.current_method = prev_method
        self.method_uses_self = prev_uses_self

    # --- STATE MUTATION OUTSIDE __init__ ---
    def visit_Assign(self, node: ast.Assign):
        if self.current_class and self.current_method and self.current_method.name != "__init__":
            for target in node.targets:
                if isinstance(target, ast.Attribute) and get_full_name(target.value) == "self":
                    self.issues.append((
                        target.lineno, target.col_offset,
                        f"Mutation outside `__init__`: attribute `self.{target.attr}` created or modified in `{self.current_method.name}`."
                    ))
        self.generic_visit(node)

    # --- TYPE(X) == Y ---
    def visit_Compare(self, node: ast.Compare):
        for left_candidate in [node.left]:
            if isinstance(left_candidate, ast.Call) and get_full_name(left_candidate.func) == "type":
                for op in node.ops:
                    if isinstance(op, (ast.Eq, ast.Is)):
                        self.issues.append((
                            node.lineno, node.col_offset,
                            "Direct comparison with `type()` — breaks the Liskov Substitution Principle."
                        ))
        self.generic_visit(node)


def categorize_issue(msg: str) -> str:
    """Classifies the issue message into a canonical category."""
    if "dict[str," in msg or "Dict[str," in msg:
        return "Primitive Obsession (Dict[str, Any])"
    if "getattr()" in msg:
        return "Introspection (getattr)"
    if "hasattr()" in msg or "setattr()" in msg:
        return "Introspection (hasattr/setattr)"
    if "isinstance()" in msg:
        return "isinstance() outside Factory"
    if "Use of `Any`" in msg or "Use of `typing.Any`" in msg:
        return "Type Bypass (Any)"
    if "typed as Option(al)" in msg:
        return "Option(al) in argument"
    if "fake dict backdoor" in msg:
        return "Fake Dict Backdoor (__getitem__/get/to_dict)"
    if "obsolete forward reference" in msg or "use `Self`" in msg:
        return "Obsolete Forward Ref (Quoted type / Self)"
    if "Mutation outside `__init__`" in msg:
        return "State mutation outside __init__"
    if "never uses `self`" in msg:
        return "Logic outside class (no-self)"
    if "@staticmethod" in msg:
        return "@staticmethod"
    if "Law of Demeter" in msg:
        return "Law of Demeter"
    if "God Class" in msg:
        return "God Class (>20 methods)"
    if "Direct comparison with `type()`" in msg:
        return "type() comparison (Liskov)"
    if "Direct access to `__dict__`" in msg:
        return "Direct access to __dict__ (Encapsulation)"
    return "Other"


def get_module_name(file_path: Path, root_path: Path) -> str:
    """Determines the Python module / enclosing package name."""
    try:
        rel = file_path.resolve().relative_to(root_path.resolve())
        parent = rel.parent
        if str(parent) == ".":
            return "(root)"
        return ".".join(parent.parts)
    except ValueError:
        return file_path.parent.name or "(root)"


def format_bar(val: int, max_val: int, length: int = 20) -> str:
    if max_val <= 0:
        return "░" * length
    filled = int(round((val / max_val) * length))
    filled = min(length, max(0, filled))
    return "█" * filled + "░" * (length - filled)


def scan(
    target_path: str,
    summary_only: bool = False,
    top_n: int = 15,
    filter_category: str | None = None,
    no_color: bool = False,
):
    path = Path(target_path).resolve()
    files = sorted(list(path.rglob("*.py")) if path.is_dir() else [path])

    # ANSI colors
    if no_color or not sys.stdout.isatty():
        C_RESET = ""
        C_BOLD = ""
        C_RED = ""
        C_GREEN = ""
        C_YELLOW = ""
        C_CYAN = ""
        C_MAGENTA = ""
        C_GRAY = ""
    else:
        C_RESET = "\033[0m"
        C_BOLD = "\033[1m"
        C_RED = "\033[91m"
        C_GREEN = "\033[92m"
        C_YELLOW = "\033[93m"
        C_CYAN = "\033[96m"
        C_MAGENTA = "\033[95m"
        C_GRAY = "\033[90m"

    file_issues: dict[Path, list[tuple[int, int, str, str]]] = {}
    module_issues: dict[str, list[tuple[Path, int, int, str, str]]] = {}
    category_counts: dict[str, int] = {}
    total_issues = 0
    clean_files_count = 0

    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, UnicodeDecodeError):
            continue

        visitor = FullOOPLintVisitor(str(f))
        visitor.visit(tree)

        mod_name = get_module_name(f, path if path.is_dir() else path.parent)
        if mod_name not in module_issues:
            module_issues[mod_name] = []

        annotated_issues: list[tuple[int, int, str, str]] = []
        for line, col, msg in visitor.issues:
            cat = categorize_issue(msg)
            if filter_category and filter_category.lower() not in cat.lower():
                continue

            annotated_issues.append((line, col, cat, msg))
            module_issues[mod_name].append((f, line, col, cat, msg))
            category_counts[cat] = category_counts.get(cat, 0) + 1
            total_issues += 1

            if not summary_only:
                print(f"{C_GRAY}{f}:{line}:{col}{C_RESET} -> {msg}")

        file_issues[f] = annotated_issues
        if not annotated_issues:
            clean_files_count += 1

    # =========================================================================
    # STATISTICS DISPLAY
    # =========================================================================
    total_files = len(files)
    impacted_files = total_files - clean_files_count
    clean_pct = (clean_files_count / total_files * 100) if total_files > 0 else 100.0

    print(f"\n{C_BOLD}{'=' * 80}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN} SIMPULSE OOP & CLEAN CODE LINTER — STATISTICAL REPORT{C_RESET}")
    print(f"{C_BOLD}{'=' * 80}{C_RESET}\n")

    # 1. Global Summary
    status_color = C_GREEN if total_issues == 0 else (C_YELLOW if total_issues < 50 else C_RED)
    print(f"{C_BOLD}► GLOBAL SUMMARY{C_RESET}")
    print(f"  • Analyzed target     : {C_BOLD}{path}{C_RESET}")
    print(f"  • Scanned files       : {C_BOLD}{total_files}{C_RESET}")
    print(f"  • Clean files (0 bugs): {C_GREEN}{clean_files_count}{C_RESET} ({clean_pct:.1f}%)")
    print(f"  • Impacted files      : {C_YELLOW if impacted_files else C_GREEN}{impacted_files}{C_RESET}")
    print(f"  • Total issues        : {status_color}{C_BOLD}{total_issues}{C_RESET}\n")

    # 2. Statistics by Rule Category
    if category_counts:
        print(f"{C_BOLD}► ISSUES BY CATEGORY / RULE ({len(category_counts)} active){C_RESET}")
        sorted_cats = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        max_cat_len = max(len(cat) for cat, _ in sorted_cats)
        max_count = max(count for _, count in sorted_cats)

        for cat, count in sorted_cats:
            bar = format_bar(count, max_count, 18)
            pct = (count / total_issues * 100) if total_issues > 0 else 0
            print(f"  {cat:<{max_cat_len}} : {C_BOLD}{count:>5}{C_RESET} ({pct:>5.1f}%) {C_MAGENTA}{bar}{C_RESET}")
        print()

    # 3. Statistics by Module / Package
    if module_issues:
        print(f"{C_BOLD}► ISSUES BY MODULE / PACKAGE ({len(module_issues)} modules){C_RESET}")
        sorted_mods = sorted(
            module_issues.items(),
            key=lambda item: len(item[1]),
            reverse=True
        )

        mod_table_data = []
        for mod, m_issues in sorted_mods:
            # Number of unique files impacted in this module
            mod_files = {iss[0] for iss in m_issues}
            mod_table_data.append((mod, len(m_issues), len(mod_files)))

        active_mods = [m for m in mod_table_data if m[1] > 0]
        clean_mods = [m for m in mod_table_data if m[1] == 0]

        max_mod_len = max((len(m[0]) for m in active_mods), default=len("Module"))
        max_mod_len = max(max_mod_len, len("Module"))

        print(f"  {C_GRAY}{'Module':<{max_mod_len}}  {'Issues':>9}  {'Files':>8}{C_RESET}")
        print(f"  {'-' * max_mod_len}  {'-' * 9}  {'-' * 8}")
        for mod, count, f_count in active_mods:
            c_color = C_YELLOW if count < 20 else C_RED
            print(f"  {mod:<{max_mod_len}}  {c_color}{count:>9}{C_RESET}  {f_count:>8}")
        if clean_mods:
            print(f"\n  {C_GREEN}✓ {len(clean_mods)} module(s) 100% clean (0 issues):{C_RESET} {', '.join(m[0] for m in clean_mods)}")
        print()

    # 4. Top Impacted Files
    files_with_issues = [(f, len(iss)) for f, iss in file_issues.items() if len(iss) > 0]
    files_with_issues.sort(key=lambda x: x[1], reverse=True)

    if files_with_issues:
        display_count = len(files_with_issues) if top_n <= 0 else min(top_n, len(files_with_issues))
        print(f"{C_BOLD}► TOP {display_count} MOST IMPACTED FILES (out of {len(files_with_issues)}){C_RESET}")

        try:
            display_files = [
                (str(f.relative_to(path if path.is_dir() else path.parent)), count)
                for f, count in files_with_issues[:display_count]
            ]
        except ValueError:
            display_files = [(f.name, count) for f, count in files_with_issues[:display_count]]

        max_fname_len = max(len(f) for f, _ in display_files)
        max_fname_len = max(max_fname_len, len("File"))

        print(f"  {C_GRAY}{'File':<{max_fname_len}}  {'Issues':>9}{C_RESET}")
        print(f"  {'-' * max_fname_len}  {'-' * 9}")
        for fname, count in display_files:
            c_color = C_YELLOW if count < 20 else C_RED
            print(f"  {fname:<{max_fname_len}}  {c_color}{C_BOLD}{count:>9}{C_RESET}")
        print()

    print(f"{C_BOLD}{'=' * 80}{C_RESET}\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="SimPulse OOP & Clean Code Linter — Static analysis and OOP design cleanliness metrics."
    )
    parser.add_argument("target", help="Path to the file or directory to analyze")
    parser.add_argument(
        "--summary-only", "-s",
        action="store_true",
        help="Display summary statistical tables only (without line-by-line details)",
    )
    parser.add_argument(
        "--top", "-t",
        type=int,
        default=15,
        help="Number of files to include in top issues (0 = all, default: 15)",
    )
    parser.add_argument(
        "--category", "-c",
        type=str,
        default=None,
        help="Filter issues by a specific category (e.g., Any, Option, Dict, etc.)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes in terminal",
    )

    args = parser.parse_args()
    scan(
        target_path=args.target,
        summary_only=args.summary_only,
        top_n=args.top,
        filter_category=args.category,
        no_color=args.no_color,
    )