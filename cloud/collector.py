"""Цикл сбора: раз в STEAM_INTERVAL секунд (по умолчанию ровно каждую минуту) берёт цены всех
кейсов со Steam и кладёт в буфер. При 429 увеличивает паузу, пока Steam не отпустит."""
import asyncio
import logging
import time

from common.steam import SteamRateLimited, fetch_cases, make_client

from . import config
from .buffer import Buffer

log = logging.getLogger("collector")


async def run(buf: Buffer):
    interval = config.STEAM_INTERVAL
    backoff = 0
    last_prune = 0.0
    async with make_client(config.STEAM_PROXY) as client:
        while True:
            now = time.time()
            ts = int(now) - int(now) % 60
            try:
                ticks, items = await fetch_cases(client, ts)
                if not ticks:
                    raise RuntimeError("Steam вернул пустой список кейсов")
                n = await asyncio.to_thread(buf.save, ticks, items)
                await asyncio.to_thread(buf.log_fetch, ts, True, len(ticks))
                log.info("сохранено %d цен (новых %d)", len(ticks), n)
                backoff = 0
            except SteamRateLimited as e:
                backoff = min(max(backoff * 2, 120), 900)
                log.warning("%s, пауза %d c", e, backoff)
                await asyncio.to_thread(buf.log_fetch, ts, False, 0, str(e))
            except Exception as e:  # сеть, 5xx, неожиданный ответ: пропускаем цикл
                log.warning("ошибка: %r", e)
                await asyncio.to_thread(buf.log_fetch, ts, False, 0, repr(e)[:500])
            if time.time() - last_prune > 3600:
                removed = await asyncio.to_thread(buf.prune, config.RETENTION_HOURS, config.MAX_DAYS)
                last_prune = time.time()
                if removed:
                    log.info("из буфера удалено %d старых записей", removed)
            # Следующий запуск — на границе следующего интервала (или после паузы при 429).
            await asyncio.sleep(backoff or interval - (time.time() % interval))
