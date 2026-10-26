"""Облачный сервис: сборщик в фоне + API, через который дом забирает данные из буфера.

Запуск: uvicorn cloud.server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from . import collector, config
from .buffer import Buffer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
buf = Buffer(config.BUFFER_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.API_TOKEN:
        raise RuntimeError("Задайте переменную окружения API_TOKEN")
    task = asyncio.create_task(collector.run(buf))
    yield
    task.cancel()


app = FastAPI(title="CS2 case collector (cloud)", lifespan=lifespan)


def auth(authorization: str = Header("")):
    if not secrets.compare_digest(authorization, f"Bearer {config.API_TOKEN}"):
        raise HTTPException(401, "bad token")


@app.get("/health")
def health():
    """Без токена: жив ли сервис и когда последний раз удалось получить цены."""
    s = buf.stats()
    return {"ok": True, "last_success_at": s["last_success_at"], "pending_ticks": s["pending_ticks"]}


@app.get("/api/stats", dependencies=[Depends(auth)])
def stats():
    return buf.stats()


@app.get("/api/ticks", dependencies=[Depends(auth)])
def ticks(after_id: int = 0, limit: int = Query(5000, le=20000)):
    return buf.read(after_id, limit)


@app.get("/api/sales", dependencies=[Depends(auth)])
def sales(after_id: int = 0, limit: int = Query(5000, le=20000)):
    return buf.read_sales(after_id, limit)


@app.get("/api/item_days", dependencies=[Depends(auth)])
def item_days(after_id: int = 0, limit: int = Query(5000, le=20000)):
    return buf.read_item_days(after_id, limit)


class Ack(BaseModel):
    up_to_id: int | None = None        # цены (ticks)
    sales_up_to_id: int | None = None  # история продаж
    items_up_to_id: int | None = None  # дневные цены предметов из кейсов


@app.post("/api/ack", dependencies=[Depends(auth)])
def ack(body: Ack):
    if body.up_to_id is not None:
        buf.ack(body.up_to_id)
    if body.sales_up_to_id is not None:
        buf.ack(body.sales_up_to_id, "sales_acked_id")
    if body.items_up_to_id is not None:
        buf.ack(body.items_up_to_id, "items_acked_id")
    return {"ok": True}
