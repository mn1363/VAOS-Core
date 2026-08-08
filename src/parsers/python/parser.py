"""`Parser` implementation for Python source files.

Parsing is delegated entirely to the standard library `ast` module rather than a hand-written
grammar, unlike the four other language parsers in this package. Python ships its own exact,
always-in-sync parser as part of the interpreter running this code, so reimplementing one with
regular expressions -- as the other four languages do, for lack of an equivalent zero-dependency
option -- would be strictly worse: slower to write, harder to keep correct, and needlessly
approximate where an exact answer is already available for free.
"""

import ast

from src.domain.entities import SourceLanguage

from ..base import (
    ParsedClass,
    ParsedExport,
    ParsedFunction,
    ParsedImport,
    ParsedSymbol,
    Parser,
    ParseResult,
    SymbolKind,
    build_file_metadata,
    has_extension,
    require_relative_path,
)

#: File extensions `PythonParser.supports` recognizes.
_EXTENSIONS = (".py", ".pyi")

#: `ast` node types that introduce a function scope, sharing one code path since they differ only
#: in `is_async`.
_FunctionDef = ast.FunctionDef | ast.AsyncFunctionDef


class PythonParser(Parser):
    """Extracts modules, classes, functions, imports, exports, and symbols from Python source.

    `__all__`, when present at module scope, is treated as the file's export list -- Python's
    closest equivalent to an explicit `export` keyword. `modules` is always empty: Python has no
    construct for declaring a nested module boundary within a single file (see
    `parsers.base.ParsedModule`).
    """

    @property
    def language(self) -> SourceLanguage:
        """The language this parser produces `ParseResult` entries for.

        Returns:
            `SourceLanguage.PYTHON`.
        """
        return SourceLanguage.PYTHON

    def supports(self, relative_path: str) -> bool:
        """Report whether `relative_path` has a Python extension.

        Args:
            relative_path: Path of the candidate file.

        Returns:
            True if `relative_path` ends with `.py` or `.pyi`.
        """
        return has_extension(relative_path, _EXTENSIONS)

    def parse(self, *, relative_path: str, content: str) -> ParseResult:
        """Parse Python `content` into a `ParseResult`.

        Args:
            relative_path: Path of the file `content` was read from.
            content: The file's full text content.

        Returns:
            A successful result, or a failed result if `content` has a syntax error.

        Raises:
            ValidationError: If `relative_path` is blank.
        """
        require_relative_path(relative_path)
        try:
            tree = ast.parse(content, filename=relative_path)
        except (SyntaxError, ValueError) as exc:
            return ParseResult.failed(
                relative_path=relative_path,
                language=SourceLanguage.PYTHON,
                error_message=f"syntax error: {exc}",
            )

        metadata = build_file_metadata(
            relative_path=relative_path, language=SourceLanguage.PYTHON, content=content
        )
        classes = _extract_classes(tree)
        functions = _extract_functions(tree)
        imports = _extract_imports(tree)
        exports = _extract_exports(tree)
        symbols = _build_symbols(classes, functions)

        return ParseResult.ok(
            relative_path=relative_path,
            language=SourceLanguage.PYTHON,
            metadata=metadata,
            classes=classes,
            functions=functions,
            imports=imports,
            exports=exports,
            symbols=symbols,
        )


def _extract_imports(tree: ast.Module) -> tuple[ParsedImport, ...]:
    """Collect every `import`/`from ... import` statement anywhere in `tree`.

    Every statement is collected regardless of nesting depth (module scope, inside a function,
    inside `if TYPE_CHECKING:`, inside `try:`/`except ImportError:`), since all of these are
    genuine imports the file depends on, not something narrower to filter by scope.

    Args:
        tree: The module's parsed syntax tree.

    Returns:
        Every import statement found, in the order encountered.
    """
    imports: list[ParsedImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(
                    ParsedImport(module=alias.name, alias=alias.asname, line_number=node.lineno)
                )
        elif isinstance(node, ast.ImportFrom):
            module = ("." * node.level) + (node.module or "")
            for alias in node.names:
                imports.append(
                    ParsedImport(
                        module=module,
                        imported_names=(alias.name,),
                        alias=alias.asname,
                        is_relative=node.level > 0,
                        line_number=node.lineno,
                    )
                )
    return tuple(imports)


def _extract_exports(tree: ast.Module) -> tuple[ParsedExport, ...]:
    """Collect the names listed in a module-scope `__all__` assignment, if present.

    Args:
        tree: The module's parsed syntax tree.

    Returns:
        One `ParsedExport` per string literal found in `__all__`, or an empty tuple if the
        module defines no `__all__`.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.List | ast.Tuple):
            continue
        return tuple(
            ParsedExport(name=element.value, line_number=node.lineno)
            for element in value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return ()


def _extract_classes(tree: ast.Module) -> tuple[ParsedClass, ...]:
    """Collect every module-scope class definition.

    Nested classes (a class defined inside another class or a function) are not collected as
    separate top-level entries; they remain reachable via their own docstring/body but are not
    independently reported, matching this layer's file-level, not deeply-recursive, scope.

    Args:
        tree: The module's parsed syntax tree.

    Returns:
        Every module-scope class, in source order.
    """
    classes: list[ParsedClass] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = tuple(
            _build_function(item, is_method=True)
            for item in node.body
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
        )
        classes.append(
            ParsedClass(
                name=node.name,
                base_classes=tuple(ast.unparse(base) for base in node.bases),
                methods=methods,
                decorators=tuple(ast.unparse(dec) for dec in node.decorator_list),
                docstring=ast.get_docstring(node),
                line_number=node.lineno,
            )
        )
    return tuple(classes)


def _extract_functions(tree: ast.Module) -> tuple[ParsedFunction, ...]:
    """Collect every module-scope function definition (methods are reported on their class).

    Args:
        tree: The module's parsed syntax tree.

    Returns:
        Every module-scope function, in source order.
    """
    return tuple(
        _build_function(node, is_method=False)
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def _build_function(node: _FunctionDef, *, is_method: bool) -> ParsedFunction:
    """Build a `ParsedFunction` from a `FunctionDef`/`AsyncFunctionDef` node.

    Args:
        node: The function or method's syntax node.
        is_method: Whether `node` was found inside a class body.

    Returns:
        A `ParsedFunction` describing `node`.
    """
    return ParsedFunction(
        name=node.name,
        parameters=_format_parameters(node.args),
        return_type=ast.unparse(node.returns) if node.returns is not None else None,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_method=is_method,
        decorators=tuple(ast.unparse(dec) for dec in node.decorator_list),
        docstring=ast.get_docstring(node),
        line_number=node.lineno,
    )


def _format_parameters(args: ast.arguments) -> tuple[str, ...]:
    """Render each parameter of a function signature as one source-text string.

    Args:
        args: The function's argument specification.

    Returns:
        One formatted string per parameter (e.g. `"x: int = 0"`, `"*args"`, `"**kwargs"`), plus
        a bare `"*"` separator when the function has keyword-only parameters but no `*args`.
    """
    parameters: list[str] = []
    positional = [*args.posonlyargs, *args.args]
    padding = [None] * (len(positional) - len(args.defaults))
    positional_defaults: list[ast.expr | None] = [*padding, *args.defaults]
    for arg, default in zip(positional, positional_defaults, strict=True):
        parameters.append(_format_parameter(arg, default))

    if args.vararg is not None:
        parameters.append(_format_parameter(args.vararg, None, prefix="*"))
    elif args.kwonlyargs:
        parameters.append("*")

    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        parameters.append(_format_parameter(arg, default))

    if args.kwarg is not None:
        parameters.append(_format_parameter(args.kwarg, None, prefix="**"))

    return tuple(parameters)


def _format_parameter(arg: ast.arg, default: ast.expr | None, *, prefix: str = "") -> str:
    """Render one parameter, with its annotation and default if present, as source text.

    Args:
        arg: The parameter's syntax node.
        default: The parameter's default value expression, if any.
        prefix: Text to prepend, e.g. `"*"` for `*args` or `"**"` for `**kwargs`.

    Returns:
        The formatted parameter, e.g. `"x: int = 0"`.
    """
    text = f"{prefix}{arg.arg}"
    if arg.annotation is not None:
        text += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        text += f" = {ast.unparse(default)}"
    return text


def _build_symbols(
    classes: tuple[ParsedClass, ...], functions: tuple[ParsedFunction, ...]
) -> tuple[ParsedSymbol, ...]:
    """Build the flat symbol table from already-extracted classes and functions.

    Args:
        classes: Classes already extracted by `_extract_classes`.
        functions: Functions already extracted by `_extract_functions`.

    Returns:
        One `ParsedSymbol` per class, per module-scope function, and per method, in that order.
    """
    symbols: list[ParsedSymbol] = []
    for cls in classes:
        symbols.append(
            ParsedSymbol(name=cls.name, kind=SymbolKind.CLASS, line_number=cls.line_number)
        )
        for method in cls.methods:
            symbols.append(
                ParsedSymbol(
                    name=method.name, kind=SymbolKind.METHOD, line_number=method.line_number
                )
            )
    for function in functions:
        symbols.append(
            ParsedSymbol(
                name=function.name, kind=SymbolKind.FUNCTION, line_number=function.line_number
            )
        )
    return tuple(symbols)
