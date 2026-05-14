"""Потоковая выдача CSV с BOM для Excel."""

from collections.abc import Iterator
import csv
import io


def stream_csv(rows_iter: Iterator[list[object]], header: list[str]) -> Iterator[bytes]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    yield "\ufeff".encode("utf-8")
    chunk = buf.getvalue()
    buf.seek(0)
    buf.truncate(0)
    yield chunk.encode("utf-8")
    for row in rows_iter:
        w.writerow(row)
        chunk = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        yield chunk.encode("utf-8")
