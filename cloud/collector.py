"""Циклы сбора.

prices:  раз в STEAM_INTERVAL секунд (по умолчанию каждую минуту) минимальные цены и лоты всех кейсов.
history: раз в HISTORY_INTERVAL секунд (по умолчанию раз в час) история продаж каждого кейса —
         медиана и число продаж по часам. Первый проход догружает всю историю за годы.
При 429 оба цикла увеличивают паузу, пока Steam не отпустит."""
import asyncio
import logging
import time

from common.steam import SteamAuthError, SteamRateLimited, SteamWrongCurrency, fetch_cases, fetch_price_history, make_client

from . import config
from .buffer import Buffer

log = logging.getLogger("collector")


async def run(buf: Buffer):
    async with make_client(config.STEAM_PROXY) as client:
        tasks = [run_prices(buf, client)]
        if config.STEAM_LOGIN_SECURE:
            tasks.append(run_history(buf, client))
        else:
            log.info("STEAM_LOGIN_SECURE не задан: история продаж не собирается")
        await asyncio.gather(*tasks)


async def run_history(buf: Buffer, client):
    await asyncio.sleep(20)  # даём циклу цен первым заполнить список кейсов
    while True:
        started = time.time()
        names = await asyncio.to_thread(buf.case_names)
        done, error = 0, None
        for name in names:
            try:
                points = await fetch_price_history(client, name, config.STEAM_LOGIN_SECURE)
                n = await asyncio.to_thread(buf.save_sales, name, points)
                done += 1
                log.info("история %s: %d точек, новых %d", name, len(points), n)
            except (SteamAuthError, SteamWrongCurrency) as e:
                error = str(e)
                log.error("%s", e)
                break  # без рабочего cookie нет смысла перебирать остальные кейсы
            except SteamRateLimited as e:
                error = str(e)
                log.warning("%s, прерываю проход истории", e)
                await asyncio.sleep(300)
                break
            except Exception as e:
                error = repr(e)[:300]
                log.warning("история %s: ошибка %r", name, e)
            await asyncio.sleep(config.HISTORY_PAUSE)
        if done:
            await asyncio.to_thread(buf.set_state, "history_ok_at", str(int(time.time())))
        await asyncio.to_thread(buf.set_state, "history_error", error)
        await asyncio.sleep(max(60, config.HISTORY_INTERVAL - (time.time() - started)))


async def run_prices(buf: Buffer, client):
    interval = config.STEAM_INTERVAL
    backoff = 0
    last_prune = 0.0
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
