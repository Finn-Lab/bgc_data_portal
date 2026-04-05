"""Helpers for bulk-loading TSV data into PostgreSQL via COPY FROM."""

from __future__ import annotations

import csv
import io
import logging
from typing import IO, Callable, Sequence

from django.db import connection

logger = logging.getLogger(__name__)


def copy_tsv_to_table(
    table: str,
    columns: Sequence[str],
    rows: IO[str] | list[list],
    *,
    transform: Callable[[dict], dict] | None = None,
) -> int:
    """Bulk-load rows into *table* using PostgreSQL ``COPY FROM STDIN``.

    Parameters
    ----------
    table:
        Fully-qualified table name (e.g. ``"discovery_detector"``).
    columns:
        Column names in insertion order.
    rows:
        Either an open text-mode file positioned at the first data line
        (header already consumed), or a list of lists (one per row).
    transform:
        Optional callable applied to each row dict before writing.  Return
        the (possibly mutated) dict, or ``None`` to skip the row.

    Returns
    -------
    int
        Number of rows written.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    count = 0

    if isinstance(rows, list):
        iterator = (dict(zip(columns, r)) for r in rows)
    else:
        reader = csv.DictReader(rows, delimiter="\t")
        iterator = reader

    for row_dict in iterator:
        if transform:
            row_dict = transform(row_dict)
            if row_dict is None:
                continue
        writer.writerow([row_dict.get(c, "") for c in columns])
        count += 1

    if count == 0:
        return 0

    buf.seek(0)
    col_list = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"COPY {table} ({col_list}) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '')"

    with connection.cursor() as cursor:
        with cursor.copy(copy_sql) as copy:
            while chunk := buf.read(65536):
                copy.write(chunk)

    logger.info("COPY %s: %d rows", table, count)
    return count


def truncate_tables(tables: Sequence[str]) -> None:
    """TRUNCATE the given tables with CASCADE."""
    if not tables:
        return
    joined = ", ".join(tables)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {joined} CASCADE")
    logger.info("TRUNCATED: %s", joined)
