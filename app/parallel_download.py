"""Bounded, ordered Telegram reads using the account's existing client/sender."""
import asyncio
import math
from contextlib import AsyncExitStack, asynccontextmanager
import inspect

PART_SIZE = 512 * 1024


@asynccontextmanager
async def managed(iterator):
    if hasattr(iterator, '__aenter__'):
        async with iterator as entered:
            yield entered
    else:
        try:
            yield iterator
        finally:
            close = getattr(iterator, 'aclose', None) or getattr(iterator, 'close', None)
            if close:
                result = close()
                if inspect.isawaitable(result): await result


async def iter_file(client, file, offset, total, parts=3):
    parts = max(1, min(4, int(parts)))
    if total and offset >= total:
        return
    parallel = parts > 1 and total - offset >= 8 * 1024 * 1024
    # An unaligned offset makes Telethon fetch two blocks for every subsequent
    # chunk. Finish only the leading block, then keep all following reads aligned.
    if total - offset > PART_SIZE and offset % PART_SIZE:
        skip = offset % PART_SIZE
        start = offset - skip
        async with managed(client.iter_download(file, offset=start, limit=1,
                request_size=PART_SIZE, chunk_size=PART_SIZE, file_size=total)) as iterator:
            try: chunk = await anext(iterator)
            except StopAsyncIteration:
                raise ConnectionError('Telegram 续传分片提前结束') from None
            if len(chunk) != min(PART_SIZE, total - start):
                raise ConnectionError('Telegram 续传分片长度不完整')
        yield chunk[skip:]
        offset += len(chunk) - skip
        if offset >= total:
            return
    if not parallel:
        async with managed(client.iter_download(file, offset=offset, request_size=PART_SIZE,
                            chunk_size=PART_SIZE, file_size=total or None)) as iterator:
            async for chunk in iterator:
                yield chunk
        return
    pending = []
    async with AsyncExitStack() as stack:
        try:
            for lane in range(parts):
                start = offset + lane * PART_SIZE
                if start >= total:
                    break
                count = math.ceil((total - start) / (PART_SIZE * parts))
                iterator = client.iter_download(file, offset=start, stride=PART_SIZE * parts,
                    limit=count, request_size=PART_SIZE, chunk_size=PART_SIZE, file_size=total)
                iterator = await stack.enter_async_context(managed(iterator))
                pending.append([iterator, count, asyncio.create_task(anext(iterator))])
            remaining = total - offset
            while pending:
                for entry in list(pending):
                    iterator, count, task = entry
                    try:
                        chunk = await task
                    except StopAsyncIteration:
                        raise ConnectionError('Telegram 分片提前结束，保留已写入数据等待续传') from None
                    expected = min(PART_SIZE, remaining)
                    if len(chunk) != expected:
                        raise ConnectionError('Telegram 分片长度不完整，保留已写入数据等待续传')
                    yield chunk
                    remaining -= len(chunk)
                    if count > 1:
                        entry[1] -= 1
                        entry[2] = asyncio.create_task(anext(iterator))
                    else:
                        pending.remove(entry)
        finally:
            tasks = [entry[2] for entry in pending]
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
