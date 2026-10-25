"""Tests für die reinen Rechenmodule (ohne Home Assistant lauffähig).

Aufruf:  python -m pytest tests/   oder   python tests/test_pure.py
"""
import importlib, os, sys, types
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "custom_components", "spotty")
# Paket ohne __init__.py laden (das würde homeassistant importieren)
pkg = types.ModuleType("spotty"); pkg.__path__ = [PKG]; sys.modules["spotty"] = pkg
pricing = importlib.import_module("spotty.pricing")
profile = importlib.import_module("spotty.profile")

TZ = ZoneInfo("Europe/Vienna")
DATA = os.path.join(ROOT, "tests", "data")


def read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return f.read()


def test_csv_herbst_umstellung_25h():
    slots = pricing.parse_payload(read("preise_herbst.csv"))
    heute = [s for s in slots if s.start.astimezone(TZ).date().isoformat() == "2026-10-25"]
    assert len(heute) == 100, len(heute)  # 25 Stunden
    assert all(s.end - s.start == timedelta(minutes=15) for s in slots)


def test_csv_fruehling_23h():
    slots = pricing.parse_payload(read("preise_fruehling.csv"))
    tag = [s for s in slots if s.start.astimezone(TZ).date().isoformat() == "2026-03-29"]
    assert len(tag) == 92, len(tag)  # 23 Stunden


def test_spotty_json_und_fremdformate():
    js = '[{"from":"2026-10-25T10:00:00+01:00","to":"2026-10-25T10:15:00+01:00","price":12.5},' \
         '{"from":"2026-10-25T10:15:00+01:00","to":"2026-10-25T10:30:00+01:00","price":11.0}]'
    s = pricing.parse_payload(js)
    assert len(s) == 2 and s[0].price == 12.5 and s[0].start.tzinfo == timezone.utc
    nested = '{"meta":1,"data":[{"start_time":1761382800000,"marketprice":95.3}]}'
    s = pricing.parse_payload(nested, factor=0.1)  # EUR/MWh -> ct/kWh
    assert abs(s[0].price - 9.53) < 1e-9
    semi = "Zeit;Preis\n25.10.2026 10:00;12,34\n25.10.2026 11:00;10,00\n"
    s = pricing.parse_payload(semi, default_tz=TZ)
    assert s[0].price == 12.34 and s[1].end - s[1].start == timedelta(hours=1)
    try:
        pricing.parse_payload('[{"foo":1,"bar":2}]'); raise AssertionError
    except pricing.PriceParseError as e:
        assert "foo" in str(e)


def _profil(name):
    samples = profile.parse_history_csv(read(name))
    return profile.build_profile(samples, standby_w=3.0)


def test_profil_aus_ha_export():
    w = _profil("geschirrspueler.csv")
    assert 100 <= len(w) <= 110
    assert abs(profile.energy_kwh(w) - 0.70) < 0.02


def test_profil_nur_bei_aenderung_gemeldet():
    t0 = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    # 2000 W für 10 min, nur zwei Meldungen
    w = profile.build_profile([(t0, 2000.0), (t0 + timedelta(minutes=10), 0.0)], 3.0,
                              end=t0 + timedelta(minutes=30))
    assert len(w) == 10 and abs(profile.energy_kwh(w) - 2000 / 6000) < 1e-9


def test_optimierung_ueber_mitternacht_und_dst():
    slots = pricing.parse_payload(read("preise_fruehling.csv"))
    w = _profil("geschirrspueler.csv")
    now = datetime(2026, 3, 29, 13, 0, 5, tzinfo=TZ).astimezone(timezone.utc)
    r = pricing.optimal_start(slots, w, now)
    # Brute-Force-Kontrolle Minute für Minute
    base = pricing.ceil_minute(now)
    def price_at(t):
        return next(s.price for s in slots if s.start <= t < s.end)
    best = None
    for k in range(0, int((slots[-1].end - base).total_seconds() // 60) - len(w) + 1):
        st = base + timedelta(minutes=k)
        c = sum(x * price_at(st + timedelta(minutes=i)) for i, x in enumerate(w)) / 60000
        if best is None or c < best[1] - 1e-9:
            best = (st, c)
    assert r.start == best[0] and abs(r.cost_ct - best[1]) < 1e-6, (r, best)
    assert r.cost_now_ct >= r.cost_ct and r.saving_ct >= 0
    print("Fruehling: Start", r.start.astimezone(TZ), "Kosten %.2f ct, jetzt %.2f ct" % (r.cost_ct, r.cost_now_ct))


def test_deadline():
    slots = pricing.parse_payload(read("preise_fruehling.csv"))
    w = _profil("waschmaschine_60C.csv")
    now = datetime(2026, 3, 29, 20, 0, tzinfo=TZ).astimezone(timezone.utc)
    dl = pricing.next_occurrence(time(6, 0), now, TZ)
    r = pricing.optimal_start(slots, w, now, deadline=dl)
    assert r.end <= dl and r.start.astimezone(TZ).date().isoformat() in ("2026-03-29", "2026-03-30")
    assert pricing.optimal_start(slots, w, now, deadline=now + timedelta(minutes=30)) is None


def test_analyse_heute():
    slots = pricing.parse_payload(read("preise_herbst.csv"))
    now = datetime(2026, 10, 25, 12, 7, tzinfo=TZ).astimezone(timezone.utc)
    snap = pricing.analyse(slots, now, TZ, 25.0, {"gs": (_profil("geschirrspueler.csv"), None), "leer": (None, None)})
    assert snap.current.start <= now < snap.current.end
    assert snap.next.start == snap.current.end
    assert snap.cheap_block and snap.cheap_block.avg_price <= snap.threshold
    assert snap.devices["leer"] is None and snap.devices["gs"].start >= now
    print("Herbst: guenstiger Block", snap.cheap_block.start.astimezone(TZ), "-", snap.cheap_block.end.astimezone(TZ),
          "| Geschirrspueler", snap.devices["gs"].start.astimezone(TZ))


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("OK", n)
