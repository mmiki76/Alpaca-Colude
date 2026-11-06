import json
import threading
import urllib.error
import urllib.request

import pandas as pd
import pytest

from alpaca_colude.bot import BotConfig, PaperBot
from alpaca_colude.dashboard import serve
from alpaca_colude.data import synthetic_bars
from alpaca_colude.exchange import (ALLOWED_BASES, BinanceError, BinanceFuturesTestnet, SimExchange, SymbolRules,
                                    fmt, parse_rules, round_to, sign_query)
from alpaca_colude.live import BEST_PARAMS, LiveScanner, ScannerState

DF = synthetic_bars(1200, seed=19)          # 5 trade-uri short cu parametrii strategiei (SL 2%, TP 5%)
RULES = SymbolRules(tick=0.01, step=0.001, min_qty=0.001, min_notional=5.0)


def make_bot(df=DF, cfg=None, **sim_kw):
    cfg = cfg or BotConfig(symbol="VETUSDT")
    ex = SimExchange(rules=RULES, **sim_kw)
    cur = {"i": 0}
    bot = PaperBot(cfg, ex, lambda c: df.iloc[: cur["i"] + 1])
    return bot, ex, cur


def replay(bot, ex, cur, df=DF, start=0, stop=None):
    for i in range(start, stop or len(df)):
        cur["i"] = i
        r = df.iloc[i]
        ex.feed(int(df.index[i].timestamp() * 1000), r.open, r.high, r.low, r.close)
        bot.tick()


# ------------------------------------------------------------- utilitare/client
def test_signature_matches_binance_docs_vector():
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert sign_query(q, secret) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_rounding_and_precision():
    assert round_to(0.0070549, 0.00001, "nearest") == 0.00705
    assert round_to(14187.9, 1, "down") == 14187.0
    assert round_to(0.0071, 0.0001, "up") == 0.0071
    assert fmt(14187.0, 1.0) == "14187" and fmt(0.00719, 0.00001) == "0.00719" and fmt(1.5, 0.001) == "1.500"


def test_parse_rules():
    info = {"symbols": [{"symbol": "VETUSDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.00001000"}, {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}
    r = parse_rules(info, "VETUSDT")
    assert (r.tick, r.step, r.min_qty, r.min_notional) == (0.00001, 1.0, 1.0, 5.0)


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._d, self.text = status, data, json.dumps(data)

    def json(self):
        return self._d


class FakeSession:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def request(self, method, url, headers=None, timeout=None, params=None):
        self.calls.append((method, url, params, headers))
        return self.handler(method, url, params)


def test_client_refuses_mainnet():
    with pytest.raises(ValueError):
        BinanceFuturesTestnet("k", "s", "https://fapi.binance.com")
    assert BinanceFuturesTestnet("k", "s", ALLOWED_BASES[1])


def test_signed_request_has_timestamp_and_valid_signature():
    sess = FakeSession(lambda m, u, p: FakeResp(200, [{"asset": "USDT", "balance": "100", "availableBalance": "90"}]))
    ex = BinanceFuturesTestnet("KEY", "SECRET", session=sess)
    assert ex.balance("USDT") == {"balance": 100.0, "available": 90.0}
    method, url, _, headers = sess.calls[0]
    query, sig = url.split("?")[1].rsplit("&signature=", 1)
    assert "timestamp=" in query and "recvWindow=" in query and headers["X-MBX-APIKEY"] == "KEY"
    assert sig == sign_query(query, "SECRET")


def test_binance_error_is_raised():
    sess = FakeSession(lambda m, u, p: FakeResp(400, {"code": -2019, "msg": "Margin is insufficient."}))
    with pytest.raises(BinanceError) as e:
        BinanceFuturesTestnet("k", "s", session=sess).set_leverage("VETUSDT", 3)
    assert e.value.code == -2019


def test_stop_uses_algo_endpoint_then_falls_back_to_classic():
    info = {"symbols": [{"symbol": "VETUSDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.00001"}, {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}

    def handler(m, url, p):
        if "exchangeInfo" in url:
            return FakeResp(200, info)
        if "/fapi/v1/algoOrder" in url:
            return FakeResp(400, {"code": -1102, "msg": "param"})
        return FakeResp(200, {"orderId": 7})
    sess = FakeSession(handler)
    out = BinanceFuturesTestnet("k", "s", session=sess).stop_close_order("VETUSDT", "BUY", 0.00719)
    assert out == {"id": 7, "via": "classic"}
    paths = [c[1].split("?")[0].replace(ALLOWED_BASES[0], "") for c in sess.calls]
    assert paths == ["/fapi/v1/exchangeInfo", "/fapi/v1/algoOrder", "/fapi/v1/order"]
    algo_url = sess.calls[1][1]
    assert "algoType=CONDITIONAL" in algo_url and "type=STOP_MARKET" in algo_url and "triggerPrice=0.00719" in algo_url


# -------------------------------------------------------------------- config
@pytest.mark.parametrize("patch", [{"leverage": 0}, {"leverage": 26}, {"leverage": 2.5}, {"stop_pct": 0}, {"symbol": "vet usdt"},
                                   {"side": "both"}, {"size_pct": 150}, {"margin_type": "X"}, {"base_url": "https://fapi.binance.com"}])
def test_config_rejects_bad_values(patch):
    bot, *_ = make_bot()
    with pytest.raises(ValueError):
        bot.update_config(patch)


def test_config_accepts_leverage_change_and_persists(tmp_path):
    cfg_path = str(tmp_path / "c.json")
    bot, ex, cur = make_bot()
    bot.cfg_path = cfg_path
    bot.update_config({"leverage": 3, "stop_pct": 1.5})
    assert bot.cfg.leverage == 3 and json.load(open(cfg_path))["stop_pct"] == 1.5


# ---------------------------------------------------------- scenariu complet
def test_full_lifecycle_matches_scanner_and_compounds():
    bot, ex, cur = make_bot()
    replay(bot, ex, cur)
    trades = bot.state.trades
    assert len(trades) >= 4
    # aceleași intrări/ieșiri ca scannerul paper pe aceleași date
    st = ScannerState(equity=100.0, last_bar=DF.index[0].isoformat())
    sc = LiveScanner(st, BEST_PARAMS, window=1500)
    sc.process(DF)
    want = [(pd.Timestamp(t["entry_time"]), t["reason"]) for t in st.trades]
    got = [(pd.Timestamp(t["entry_time"]).tz_localize("UTC"), t["reason"]) for t in trades if t["reason"] in ("STOP", "TARGET")]
    assert [w[0] for w in want][:len(got)] == [g[0] for g in got]
    assert [w[1] for w in want][:len(got)] == [g[1] for g in got]
    # mărime compusă: fiecare intrare ≈ equity de după trade-ul anterior x 98%
    prev = 100.0
    for t in trades:
        assert t["notional"] == pytest.approx(prev * 0.98, rel=0.01)
        prev = t["equity_after"]
    assert bot.state.equity == pytest.approx(prev)
    # ordinele: SL +2% și TP -5% față de prețul de fill; închise/anulate la final
    sells = [c for c in ex.calls if c[0] == "market" and c[1] == "SELL"]
    sls = [c for c in ex.calls if c[0] == "sl"]
    tps = [c for c in ex.calls if c[0] == "tp"]
    assert len(sls) == len(tps) == len(sells) >= 4
    fills = [t["entry"] for t in trades]
    for f, sl, tp in zip(fills, sls, tps):
        assert sl[2] == pytest.approx(f * 1.02, abs=0.0051)
        assert tp[3] == pytest.approx(f * 0.95, abs=0.0051)
    assert ex.pos_amt == 0 and ex.sl is None and ex.tp is None


def test_leverage_applies_to_next_entry_and_scales_size():
    bot, ex, cur = make_bot()
    i = 0
    while not (bot.state.trades and bot.state.position is None) and i < len(DF):      # până ești flat după primul trade
        replay(bot, ex, cur, start=i, stop=i + 1)
        i += 1
    n1, eq = len(bot.state.trades), bot.state.equity
    assert n1 >= 1 and ex.leverage == 1
    bot.update_config({"leverage": 3})                                                 # se aplică la următoarea intrare
    replay(bot, ex, cur, start=i)
    later = bot.state.trades[n1:]
    assert later and ex.leverage == 3
    assert later[0]["leverage"] == 3 and later[0]["notional"] == pytest.approx(eq * 0.98 * 3, rel=0.01)


def test_leverage_change_does_not_touch_open_position():
    bot, ex, cur = make_bot()
    i = 0
    while bot.state.position is None and i < len(DF):
        replay(bot, ex, cur, start=i, stop=i + 1)
        i += 1
    p = dict(bot.state.position)
    bot.update_config({"leverage": 10})
    assert bot.state.position == p and ex.leverage == 1                               # poziția deschisă rămâne la 1x


def test_stop_failure_closes_position_immediately():
    bot, ex, cur = make_bot(fail_stop=True)
    replay(bot, ex, cur)
    assert ex.pos_amt == 0
    assert any(e[1] == "error" and "SL" in e[2] for e in bot.state.events)
    assert bot.state.trades and all(t["reason"].startswith("SL EȘUAT") for t in bot.state.trades)   # contabilizat cu costuri
    assert all(t["pnl"] < 0 for t in bot.state.trades)                                                 # comision + slippage


def test_paused_and_signal_only_modes_place_no_orders():
    bot, ex, cur = make_bot()
    bot.pause()
    replay(bot, ex, cur)
    assert not [c for c in ex.calls if c[0] == "market"] and bot.state.trades == []
    bot2, ex2, cur2 = make_bot(cfg=BotConfig(trading_enabled=False))
    replay(bot2, ex2, cur2)
    assert not [c for c in ex2.calls if c[0] == "market"]
    assert any(e[1] == "signal" for e in bot2.state.events)


def test_unknown_exchange_position_blocks_entries():
    bot, ex, cur = make_bot()
    ex.pos_amt, ex.pos_entry = -5.0, 100.0
    replay(bot, ex, cur)
    assert not [c for c in ex.calls if c[0] == "market"]
    assert any("necunoscută" in e[2] for e in bot.state.events)


def test_software_guard_closes_when_exchange_stop_is_missing():
    bot, ex, cur = make_bot()
    # rulează până apare prima poziție
    i = 0
    while bot.state.position is None and i < len(DF):
        replay(bot, ex, cur, start=i, stop=i + 1)
        i += 1
    p = bot.state.position
    assert p is not None
    ex.sl = None                                           # simulează SL "acceptat dar inexistent"
    px = p["stop"] * 1.01                                  # prețul trece peste SL cu 1% (> 0,3% toleranță)
    cur["i"] = i
    ex.feed(int(DF.index[min(i, len(DF) - 1)].timestamp() * 1000) + 1, px, px, px, px)
    bot.tick()
    assert bot.state.position is None and ex.pos_amt == 0
    assert any("software" in e[2] for e in bot.state.events)


def test_state_persists_and_restart_continues(tmp_path):
    sp = str(tmp_path / "s.json")
    ex = SimExchange(rules=RULES)
    cur = {"i": 0}
    bot = PaperBot(BotConfig(), ex, lambda c: DF.iloc[: cur["i"] + 1], sp)
    replay(bot, ex, cur, stop=900)
    eq, n = bot.state.equity, len(bot.state.trades)
    bot2 = PaperBot(BotConfig(), ex, lambda c: DF.iloc[: cur["i"] + 1], sp)            # "repornire"
    assert bot2.state.equity == pytest.approx(eq) and len(bot2.state.trades) == n


# ----------------------------------------------------------------- dashboard
def http(srv, path, method="GET", body=None, headers=None):
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_dashboard_api():
    bot, ex, cur = make_bot()
    replay(bot, ex, cur, stop=900)
    srv = serve(bot, 0)
    try:
        code, body = http(srv, "/")
        assert code == 200 and b"Paper Bot" in body
        code, body = http(srv, "/api/state")
        s = json.loads(body)
        assert code == 200 and s["mode"] == "SIM" and s["config"]["leverage"] == 1 and s["stats"]["trades"] == len(bot.state.trades)
        assert set(["equity", "next_size", "position", "trades", "curve", "events", "daily", "setup"]) <= set(s)
        h = {"X-Requested-With": "dashboard", "Content-Type": "application/json"}
        assert http(srv, "/api/config", "POST", {"leverage": 4}, h)[0] == 200 and bot.cfg.leverage == 4
        assert http(srv, "/api/config", "POST", {"leverage": 4}, {"Content-Type": "application/json"})[0] == 403     # fără antet
        code, body = http(srv, "/api/config", "POST", {"leverage": 99}, h)
        assert code == 400 and "leverage" in json.loads(body)["error"] and bot.cfg.leverage == 4
        assert http(srv, "/api/config", "POST", {"base_url": "https://fapi.binance.com"}, h)[0] == 400
        assert http(srv, "/api/pause", "POST", {}, h)[0] == 200 and bot.state.paused
        assert http(srv, "/api/resume", "POST", {}, h)[0] == 200 and not bot.state.paused
        assert http(srv, "/api/state", headers={"Host": "evil.example.com"})[0] == 403
    finally:
        srv.shutdown()
