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


class FullOOPLintVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.issues: list[tuple[int, int, str]] = []
        self.current_class: ast.ClassDef | None = None
        self.current_method: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        self.method_uses_self = False

    # --- LISTE INITIALE : isinstance(), getattr(), hasattr(), setattr() ---
    def visit_Call(self, node: ast.Call):
        func_name = get_full_name(node.func)
        if func_name in {"isinstance", "getattr", "hasattr", "setattr"}:
            self.issues.append((
                node.lineno, node.col_offset,
                f"Appel à `{func_name}()` — casse le polymorphisme et l'encapsulation."
            ))
        self.generic_visit(node)

    # --- LISTE INITIALE : Dict[str, Any] / dict[str, Any] ---
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
                if key_type == "str" and val_type in {"Any", "typing.Any"}:
                    self.issues.append((
                        node.lineno, node.col_offset,
                        "Usage de `dict[str, Any]` — primitive obsession (objet métier non modélisé)."
                    ))
                    return  # Évite de déclencher l'alerte sur le Any interne

        self.generic_visit(node)

    # --- LISTE INITIALE : Any ---
    def visit_Name(self, node: ast.Name):
        if node.id == "Any":
            self.issues.append((
                node.lineno, node.col_offset,
                "Usage de `Any` — contourne le typage et le contrat d'interface."
            ))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # typing.Any
        if get_full_name(node) == "typing.Any":
            self.issues.append((
                node.lineno, node.col_offset,
                "Usage de `typing.Any` — contourne le typage et le contrat d'interface."
            ))
            return

        # Détection d'utilisation de self
        if get_full_name(node.value) == "self":
            self.method_uses_self = True

        # Accès direct à __dict__
        if node.attr == "__dict__":
            self.issues.append((
                node.lineno, node.col_offset,
                "Accès direct à `__dict__` — casse le modèle objet et l'encapsulation."
            ))

        # Loi de Déméter (Train Wreck) : a.b.c.d
        depth = 0
        curr = node
        while isinstance(curr, ast.Attribute):
            depth += 1
            curr = curr.value
        if depth >= 3:
            self.issues.append((
                node.lineno, node.col_offset,
                f"Loi de Déméter violée (profondeur {depth}) — trop forte intimité entre structures."
            ))

        self.generic_visit(node)

    # --- GOD CLASS & STRUCTURES DE CLASSE ---
    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class = self.current_class
        self.current_class = node

        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(methods) > 20:
            self.issues.append((
                node.lineno, node.col_offset,
                f"God Class : `{node.name}` expose {len(methods)} méthodes (seuil conseillé : <= 20)."
            ))

        self.generic_visit(node)
        self.current_class = prev_class

    # --- FEATURE ENVY / @staticmethod ---
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._check_method(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._check_method(node)

    def _check_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
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
                f"`@{node.name}` est un `@staticmethod` — procédure pure isolée artificiellement dans une classe."
            ))

        self.generic_visit(node)

        # Méthode d'instance ignorant self (Feature Envy / fonction déguisée)
        args = [arg.arg for arg in node.args.args]
        is_instance_method = args and args[0] == "self"
        exempt_decorators = {"staticmethod", "classmethod", "property", "abstractmethod"}
        if is_instance_method and not self.method_uses_self and not any(d in exempt_decorators for d in decorators):
            if not (len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Expr))):
                self.issues.append((
                    node.lineno, node.col_offset,
                    f"Méthode `{node.name}` n'utilise jamais `self` — logique externe à la classe."
                ))

        self.current_method = prev_method
        self.method_uses_self = prev_uses_self

    # --- MUTATION D'ÉTAT HORS __init__ ---
    def visit_Assign(self, node: ast.Assign):
        if self.current_class and self.current_method and self.current_method.name != "__init__":
            for target in node.targets:
                if isinstance(target, ast.Attribute) and get_full_name(target.value) == "self":
                    self.issues.append((
                        target.lineno, target.col_offset,
                        f"Mutation hors `__init__` : attribut `self.{target.attr}` créé ou altéré dans `{self.current_method.name}`."
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
                            "Comparaison directe avec `type()` — détruit le principe de substitution de Liskov."
                        ))
        self.generic_visit(node)


def scan(target_path: str):
    path = Path(target_path)
    files = path.rglob("*.py") if path.is_dir() else [path]
    total = 0

    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, UnicodeDecodeError):
            continue

        visitor = FullOOPLintVisitor(str(f))
        visitor.visit(tree)

        for line, col, msg in visitor.issues:
            print(f"{f}:{line}:{col} -> {msg}")
            total += 1

    print(f"\n{total} anomalie(s) détectée(s).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python full_oop_lint.py <fichier_ou_dossier>")
        sys.exit(1)
    scan(sys.argv[1])