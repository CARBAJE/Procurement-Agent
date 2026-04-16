from fastapi import FastAPI
from pydantic import BaseModel

from .core import parse_batch, parse_request
from .schemas import ParseResult

app = FastAPI(title="Beckn Intent Parser", version="1.0")


class _Query(BaseModel):
    query: str


class _Batch(BaseModel):
    queries: list[str]
    max_workers: int = 4


@app.post("/parse", response_model=ParseResult)
def parse(req: _Query) -> ParseResult:
    return parse_request(req.query)


@app.post("/parse/batch", response_model=list[ParseResult])
def batch(req: _Batch) -> list[ParseResult]:
    return parse_batch(req.queries, req.max_workers)
