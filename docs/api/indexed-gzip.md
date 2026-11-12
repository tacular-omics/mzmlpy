# Indexed gzip

Helpers for creating and detecting self-indexed `.mzML.gz` files. `index_gzip` is an alias
of `write_indexed_gzip`.

::: mzmlpy.write_indexed_gzip

Use `is_embedded_indexed_gzip` to decide whether an existing gzip file can be reused
directly or needs conversion with `write_indexed_gzip`.

::: mzmlpy.is_embedded_indexed_gzip

::: mzmlpy.IndexedGzipWriteResult

## AccessStrategy

The concrete storage route a reader chose, reported by `Mzml.access_strategy`.

::: mzmlpy.AccessStrategy
