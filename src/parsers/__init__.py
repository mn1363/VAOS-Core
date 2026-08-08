"""Parsers layer: extracts structural information from a single source file's already-read
content -- without touching the filesystem, a network, or any other layer's storage.

`parsers` answers one question: *what is structurally present in this one file?* Given a
`relative_path` (used only to select a parser and as a label) and the file's `content` as an
already-decoded string, a `Parser` extracts modules, classes, functions, imports, exports,
symbols, and file metadata -- and nothing else. It performs no business logic, no architecture
analysis, no scoring, and no graph generation; those are later phases' concerns. It also does not
read files itself (that is `collectors`/`repository`, already built) and does not persist results
(that is `storage`, a later phase) -- both are deliberately out of scope here, matching the
frozen separation between these packages.

It defines the shared `Parser` Port, the `ParseResult` outcome DTO, and every parsed-construct
DTO (`ParsedModule`, `ParsedClass`, `ParsedFunction`, `ParsedImport`, `ParsedExport`,
`ParsedSymbol`, `SymbolKind`, `FileMetadata`) in `base.py`, and provides one concrete `Parser`
per supported `SourceLanguage`: `PythonParser`, `RustParser`, `GoParser`, `TypeScriptParser`, and
`CppParser`, each in its own same-named subpackage.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.parsers.python.parser import PythonParser`); this package intentionally does not re-export a
combined surface from `__init__.py`.
"""
