"""SQLite storage backend: a single local database file, using only the standard library's
`sqlite3` module -- no additional runtime dependency. See `driver.py` for `open_connection`,
`initialize_schema`, `close_connection`, and `SqliteSourceRepositoryStore`,
`SqliteSourceFileRepository`, `SqliteAnalysisRunRepository`, `SqliteFindingRepository`.
"""
