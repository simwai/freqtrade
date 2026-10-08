# Stack: Database

- Schema design: 3NF minimum, denormalize only with documented reason; every foreign key has a matching index.
- Target: 3NF normalization. Every table has a single-column `INTEGER` primary key named `id`. Denormalization requires explicit rationale.
- Table names are singular `snake_case`. Foreign keys are `[singular_table]_id`. Indexes named `idx_[table]_[columns]`. No prefixes or suffixes.
- Naming: snake_case for tables and columns; singular table names (`user`, not `users`); singular column names for scalar fields.
- Type subset (cross-database compatible): `INTEGER`, `TEXT`, `BOOLEAN`, `REAL`. No `SERIAL`, `AUTO_INCREMENT`, `VARCHAR(n)`, `BIGINT`, `SMALLINT`, `TINYINT`, `NUMERIC`, or `DECIMAL`. Use `TEXT` with `CHECK (length(col) <= n)` for varchar semantics. For monetary values use `INTEGER` cents (avoid `DECIMAL`/`NUMERIC`).
- Timestamps are `TEXT` storing Unix epoch seconds as strings. Named `created_at`, `updated_at`, `deleted_at`.
- Every column explicit `NOT NULL` or nullable. `BOOLEAN` columns must be `NOT NULL DEFAULT false`.
- Migrations: forward-only, one change per migration, named with timestamp + description; never edit a migration after it has been applied.
- Indexes: every foreign key, every column referenced in `WHERE` for non-trivial queries, every column used in `ORDER BY` for sort. Every foreign key must have an explicit index. Add indexes for `WHERE`, `JOIN`, `ORDER BY`, `GROUP BY` columns on tables over ~1k rows.
- Queries: parameterized only; no string concatenation; `EXPLAIN ANALYZE` reviewed for queries over 100ms.
- Transactions: every multi-statement write wraps in a transaction; isolation level chosen explicitly, not defaulted.
