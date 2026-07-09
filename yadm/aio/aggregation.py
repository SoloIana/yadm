from __future__ import annotations

from typing import Any, AsyncIterator

from yadm.aggregation import BaseAggregator


class AioAggregator(BaseAggregator):
    async def __aiter__(self) -> AsyncIterator[Any]:
        async for item in self._cursor:
            yield item
