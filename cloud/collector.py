"""Циклы сбора.

prices:  раз в STEAM_INTERVAL секунд (по умолчанию каждую минуту) минимальные цены и лоты всех кейсов.
history: раз в HISTORY_INTERVAL секунд (по умолчанию раз в час) история продаж каждого кейса —
         медиана и число продаж по часам. Первый проход догружает всю историю за годы.
         Суточный токен логина продлевается сам, если задан STEAM_REFRESH_TOKEN.
При 429 оба цикла увеличивают паузу, пока Steam не отпустит."""
import asyncio
import logging
import time

from common.steam import (SteamAuthError, SteamRateLimited, fetch_cases, fetch_price_history, jwt_expires_at,
                          make_client, refresh_login_secure, split_login_cookie)

from . import config
from .buffer import Buffer

log = logging.getLogger("collector")


async def run(buf: Buffer):
    async with make_client(config.STEAM_PROXY) as client:
        tasks = [run_prices(buf, client)]
        if config.STEAM_LOGIN_SECURE or config.STEAM_REFRESH_TOKEN:
            tasks.append(run_history(buf, client))
        else:
            log.info("STEAM_LOGIN_SECURE и STEAM_REFRESH_TOKEN не заданы: история продаж не собирается")
        await asyncio.gather(*tasks)


class SteamLogin:
    """Текущий steamLoginSecure. Продлевается по refresh token за 2 часа до истечения
    и сразу после отказа Steam. Последний полученный токен хранится в буфере, чтобы
    перезапуск контейнера не требовал лишнего продления."""

    def __init__(self, buf: Buffer, client):
        self.buf, self.client = buf, client
        # Берём тот из двух токенов (сохранённый в буфере или из .env), что живёт дольше:
        # так свежий cookie, вписанный в .env руками, не перекрывается старым из буфера.
        self.value = max([buf.get_state("login_secure") or "", config.STEAM_LOGIN_SECURE], key=self._exp)

    @staticmethod
    def _exp(value: str) -> int:
        try:
            return jwt_expires_at(split_login_cookie(value)[1])
        except Exception:
            return 0

    def expires_at(self) -> int:
        return self._exp(self.value)

    async def get(self, force_refresh: bool = False) -> str:
        if config.STEAM_REFRESH_TOKEN and (force_refresh or self.expires_at() < time.time() + 7200):
            self.value = await refresh_login_secure(config.STEAM_REFRESH_TOKEN, config.STEAM_PROXY)
            await asyncio.to_thread(self.buf.set_state, "login_secure", self.value)
            log.info("токен Steam продлён до %s UTC",
                     time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.expires_at())))
        if not self.value:
            raise SteamAuthError("нет токена Steam: задайте STEAM_REFRESH_TOKEN или STEAM_LOGIN_SECURE")
        return self.value


async def run_history(buf: Buffer, client):
    await asyncio.sleep(20)  # даём циклу цен первым заполнить список кейсов
    login = SteamLogin(buf, client)
    while True:
        started = time.time()
        names = await asyncio.to_thread(buf.case_names)
        done, error = 0, None
        for name in names:
            try:
                try:
                    points = await fetch_price_history(client, name, await login.get())
                except SteamAuthError:
                    if not config.STEAM_REFRESH_TOKEN:
                        raise
                    # Steam мог отозвать токен раньше срока: продлеваем и пробуем ещё раз.
                    points = await fetch_price_history(client, name, await login.get(force_refresh=True))
                n = await asyncio.to_thread(buf.save_sales, name, points)
                done += 1
                log.info("история %s: %d точек, новых %d%s", name, len(points), n,
                         "" if not points or points[0].median_cents is not None
                         else " (медиана не в USD — сохранён только объём)")
            except SteamAuthError as e:
                error = str(e)
                log.error("%s", e)
                break  # без рабочего токена нет смысла перебирать остальные кейсы
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
        await asyncio.to_thread(buf.set_state, "login_expires_at", str(login.expires_at()))
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
