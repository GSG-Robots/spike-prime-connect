import ast_comments as ast
from pathlib import Path
import sys
from compyner.engine import ComPYner, ast_from_file


SPIKE_PRIME_MODULES = [
    "array",
    "binascii",
    "builtins",
    "cmath",
    "collections",
    "errno",
    "gc",
    "hashlib",
    "heapq",
    "io",
    "json",
    "math",
    "os",
    "random",
    "re",
    "select",
    "struct",
    "sys",
    "time",
    "zlib",
    "bluetooth",
    "machine",
    "micropython",
    "uctypes",
    "__main__",
    "_onewire",
    "firmware",
    "hub",
    "uarray",
    "ubinascii",
    "ubluetooth",
    "ucollections",
    "uerrno",
    "uhashlib",
    "uheapq",
    "uio",
    "ujson",
    "umachine",
    "uos",
    "urandom",
    "ure",
    "uselect",
    "utime",
    "utimeq",
    "uzlib",
    "spike",
    "mindstorms",
    "hub",
    "runtime",
]


class PreOptimize(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        for arg in node.args.args:
            arg.annotation = None
        for arg in node.args.posonlyargs:
            arg.annotation = None
        for arg in node.args.kwonlyargs:
            arg.annotation = None
        node.returns = None
        node = self.generic_visit(node)
        node.body = [
            stmt
            for stmt in node.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ] or [ast.copy_location(ast.Pass(), node)]
        return node

    def visit_Comment(self, node):
        return None

    def visit_AnnAssign(self, node):
        if node.value:
            return self.generic_visit(
                ast.copy_location(
                    ast.Assign(targets=[node.target], value=node.value), node
                )
            )
        else:
            return None

    def visit_Module(self, node):
        node = self.generic_visit(node)
        node.body = [
            stmt
            for stmt in node.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ] or [ast.copy_location(ast.Pass(), node)]
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef | ast.Assign:
        node = self.generic_visit(node)
        node.body = [
            stmt
            for stmt in node.body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ] or [ast.copy_location(ast.Pass(), node)]

        if len(node.body) == 1 and len(node.bases) == 1:
            return ast.Assign(
                [ast.Name(node.name, ast.Store())],
                node.bases[0],
                lineno=0,
                col_offset=0,
            )
        return node


def pre_optimize(module, name):
    return PreOptimize().visit(module)

def spike_prime_compyne(input_module: Path, slot: int = 0, debug_build: bool = False):
    sys.path.append(str(input_module.parent))
    compyner = ComPYner(
        exclude_modules=SPIKE_PRIME_MODULES,
        module_preprocessor=pre_optimize,
        # pastprocessor=past_optimize,
        require_dunder_name=debug_build,
        random_name_length=0 if debug_build else 4,
        keep_names=debug_build,
    )
    code = f"# LEGO type:standard slot:{slot} autostart\n" + compyner.compyne_from_ast(
        "__main__",
        ast_from_file(input_module),
        origin=input_module.absolute(),
    )
    sys.path.pop()
    return code
