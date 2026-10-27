"""Collection loops.

prices:  every STEAM_INTERVAL seconds (every minute by default): lowest price and listings of all cases.
history: every HISTORY_INTERVAL seconds (hourly by default): sales history of every case -
         hourly median and number of sales. The first pass backfills years of history.
         The daily login token renews itself if STEAM_REFRESH_TOKEN is set.
On HTTP 429 both loops back off until Steam lets go."""
import asyncio
import logging
import time

from common.case_contents import CRATES_URL, SKINS_URL
from common.case_contents import build as build_contents
from common.ev import daily_points
from common.steam import (
    SteamAuthError,
    SteamRateLimited,
    fetch_cases,
    fetch_price_history,
    jwt_expires_at,
    make_client,
    refresh_login_secure,
    split_login_cookie,
)

from . import config
from .buffer import Buffer

log = logging.getLogger("collector")


async def run(buf: Buffer):
    async with make_client(config.STEAM_PROXY) as client:
        tasks = [run_prices(buf, client)]
        if config.STEAM_LOGIN_SECURE or config.STEAM_REFRESH_TOKEN:
            tasks.append(run_history(buf, client))
        else:
            log.info("STEAM_LOGIN_SECURE and STEAM_REFRESH_TOKEN are not set: sales history is not collected")
        await asyncio.gather(*tasks)


class SteamLogin:
    """Current steamLoginSecure. Renewed via the refresh token 2 hours before expiry and right
    after Steam rejects it. The latest token is stored in the buffer so a container restart
    does not trigger an extra renewal."""

    def __init__(self, buf: Buffer, client):
        self.buf, self.client = buf, client
        # Use whichever of the two tokens (stored in the buffer or from .env) lives longer,
        # so a fresh cookie pasted into .env by hand is not overridden by an old one from the buffer.
        candidates = [buf.get_state("login_secure") or "", config.STEAM_LOGIN_SECURE]
        # If the refresh token belongs to another account (it was replaced), the old tokens do not fit.
        if config.STEAM_REFRESH_TOKEN:
            owner = split_login_cookie(config.STEAM_REFRESH_TOKEN)[0]
            candidates = [c for c in candidates if self._steamid(c) == owner]
        self.value = max(candidates + [""], key=self._exp)

    @staticmethod
    def _steamid(value: str) -> str | None:
        try:
            return split_login_cookie(value)[0]
        except Exception:
            return None

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
            log.info("Steam token renewed until %s UTC",
                     time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.expires_at())))
        if not self.value:
            raise SteamAuthError("no Steam token: set STEAM_REFRESH_TOKEN or STEAM_LOGIN_SECURE")
        return self.value


class Contents:
    """Case contents (for EV): downloaded once a day; on error the previous version is kept."""

    def __init__(self, client):
        self.client, self.data, self.loaded_at = client, {}, 0.0

    async def get(self) -> dict[str, dict[str, float]]:
        if time.time() - self.loaded_at > 86400:
            try:
                crates = (await self.client.get(CRATES_URL)).json()
                skins = (await self.client.get(SKINS_URL)).json()
                self.data = await asyncio.to_thread(build_contents, crates, skins)
                log.info("case contents loaded: %d cases", len(self.data))
            except Exception as e:
                log.warning("case contents failed to load: %r", e)
            self.loaded_at = time.time()
        return self.data


async def run_items(buf: Buffer, client, login: SteamLogin, contents: Contents, deadline: float):
    """Prices of items inside cases for EV: as many as fit before the next case-history pass.
    Cases are processed one by one (most liquid first), so EV appears case by case.
    A full round over ~10k items takes about a day, then it starts over."""
    cases = await asyncio.to_thread(buf.cases_by_liquidity)
    if config.EV_CASES:
        cases = [c for c in cases if c in config.EV_CASES]
    data = await contents.get()
    names = list(dict.fromkeys(n for case in cases for n in sorted(data.get(case, {}))))
    if not names:
        return
    await asyncio.to_thread(buf.set_state, "items_total", str(len(names)))
    budget = int((deadline - time.time()) / max(config.HISTORY_PAUSE, 1)) + 1
    todo = await asyncio.to_thread(buf.items_to_fetch, names, budget)
    fails = done = 0
    for name in todo:
        if time.time() > deadline:
            break
        try:
            try:
                points = await fetch_price_history(client, name, await login.get())
            except SteamAuthError:
                # Steam answers the same way for a non-existent item: renew the token and retry once.
                points = await fetch_price_history(client, name, await login.get(force_refresh=True))
            fails = 0
        except SteamRateLimited as e:
            log.warning("%s, stopping the items pass", e)
            await asyncio.sleep(300)
            return
        except Exception as e:
            fails += 1
            log.warning("prices %s: error %r", name, e)
            points = []
            if fails >= 5:  # five failures in a row - most likely a login problem, not the items
                log.error("five errors in a row, stopping the items pass")
                return
        await asyncio.to_thread(buf.save_item_days, name, daily_points(points))
        done += 1
        await asyncio.sleep(config.HISTORY_PAUSE)
    log.info("prices of items inside cases: updated %d", done)


async def run_history(buf: Buffer, client):
    await asyncio.sleep(20)  # let the price loop fill the case list first
    login = SteamLogin(buf, client)
    contents = Contents(client)
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
                    # Steam may have revoked the token early: renew and retry.
                    points = await fetch_price_history(client, name, await login.get(force_refresh=True))
                n = await asyncio.to_thread(buf.save_sales, name, points)
                done += 1
                log.info("history %s: %d points, %d new%s", name, len(points), n,
                         "" if not points or points[0].median_cents is not None
                         else " (median not in USD - only volume stored)")
            except SteamAuthError as e:
                error = str(e)
                log.error("%s", e)
                break  # without a working token there is no point trying the other cases
            except SteamRateLimited as e:
                error = str(e)
                log.warning("%s, stopping the history pass", e)
                await asyncio.sleep(300)
                break
            except Exception as e:
                error = repr(e)[:300]
                log.warning("history %s: error %r", name, e)
            await asyncio.sleep(config.HISTORY_PAUSE)
        if done:
            await asyncio.to_thread(buf.set_state, "history_ok_at", str(int(time.time())))
        await asyncio.to_thread(buf.set_state, "history_error", error)
        await asyncio.to_thread(buf.set_state, "login_expires_at", str(login.expires_at()))
        if config.ITEM_PRICES and not error:
            try:
                await run_items(buf, client, login, contents, started + config.HISTORY_INTERVAL - 60)
            except Exception as e:
                log.warning("items pass crashed: %r", e)
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
                raise RuntimeError("Steam returned an empty case list")
            n = await asyncio.to_thread(buf.save, ticks, items)
            await asyncio.to_thread(buf.log_fetch, ts, True, len(ticks))
            log.info("saved %d prices (%d new)", len(ticks), n)
            backoff = 0
        except SteamRateLimited as e:
            backoff = min(max(backoff * 2, 120), 900)
            log.warning("%s, pausing %d s", e, backoff)
            await asyncio.to_thread(buf.log_fetch, ts, False, 0, str(e))
        except Exception as e:  # network, 5xx, unexpected response: skip this cycle
            log.warning("error: %r", e)
            await asyncio.to_thread(buf.log_fetch, ts, False, 0, repr(e)[:500])
        if time.time() - last_prune > 3600:
            removed = await asyncio.to_thread(buf.prune, config.RETENTION_HOURS, config.MAX_DAYS)
            last_prune = time.time()
            if removed:
                log.info("pruned %d old rows from the buffer", removed)
        # Next run on the next interval boundary (or after the pause on 429).
        await asyncio.sleep(backoff or interval - (time.time() % interval))
