import asyncio
from contextlib import aclosing
import pytest
from app.parallel_download import iter_file,PART_SIZE

class Client:
    def __init__(self,data):self.data=data;self.active=0;self.peak=0;self.closed=0
    async def iter_download(self,file,offset=0,stride=None,limit=None,**kwargs):
        self.active+=1;self.peak=max(self.peak,self.active)
        try:
            index=0
            while offset<len(self.data) and (limit is None or index<limit):
                await asyncio.sleep(.001 if offset % (3*PART_SIZE) else .006)
                yield self.data[offset:offset+PART_SIZE]
                offset+=stride or PART_SIZE;index+=1
        finally:self.active-=1;self.closed+=1

@pytest.mark.parametrize('offset',[0,PART_SIZE,PART_SIZE+37])
def test_parallel_out_of_order_responses_emit_exact_contiguous_prefix(offset):
    data=bytes(range(251))*(10*1024*1024//251)+b'tail';client=Client(data)
    async def run():
        async with aclosing(iter_file(client,None,offset,len(data))) as chunks:
            actual=b''.join([chunk async for chunk in chunks])
        assert actual==data[offset:]
    asyncio.run(run());assert client.active==0 and client.closed==3 and client.peak<=3

def test_pause_closes_all_reads_and_resume_keeps_exact_file():
    data=b'A'*PART_SIZE+b'B'*PART_SIZE+b'C'*(9*1024*1024);client=Client(data)
    async def run():
        prefix=b''
        async with aclosing(iter_file(client,None,0,len(data))) as chunks:
            async for chunk in chunks:
                prefix+=chunk
                if len(prefix)>=2*PART_SIZE:break
        assert client.active==0
        async with aclosing(iter_file(client,None,len(prefix),len(data))) as chunks:
            return prefix+b''.join([chunk async for chunk in chunks])
    assert asyncio.run(run())==data;assert client.active==0

def test_short_read_does_not_emit_corrupt_range():
    class Short(Client):
        async def iter_download(self,file,**kwargs):yield b'incomplete'
    client=Short(b'x'*(9*1024*1024))
    async def run():
        async with aclosing(iter_file(client,None,0,len(client.data))) as chunks:
            with pytest.raises(ConnectionError):await anext(chunks)
    asyncio.run(run())
