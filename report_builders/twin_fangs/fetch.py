"""Everything the Twin Fangs report needs out of the Warcraft Logs v2 API, cached on disk.

The paging/caching machinery is the Sszorak builder's, reused rather than
copied; only the cache location differs. Delete `cache/<code>/` to refetch.
"""

from __future__ import annotations

from pathlib import Path

from report_builders.sszorak.fetch import Fetcher as _BaseFetcher

CACHE_ROOT = Path(__file__).parent / "cache"


class Fetcher(_BaseFetcher):
    def __init__(self, code: str, cache_root: Path | None = None) -> None:
        super().__init__(code, cache_root or CACHE_ROOT)
