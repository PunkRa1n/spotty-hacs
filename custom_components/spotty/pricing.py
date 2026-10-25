"""Preisdaten parsen, auswerten und Gerätestarts optimieren.

Bewusst reines Python ohne Home-Assistant-Importe: testbar ohne HA,
und keine schweren Abhängigkeiten wie pandas/numpy.
Alle Zeitpunkte intern in UTC, Preise in ct/kWh.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from statistics import median
from typing import Any

TIME_FIELDS = (
    "from", "start", "startsat", "start_time", "starttime", "datetime",
    "time", "timestamp", "date", "zeit", "von",
)
END_FIELDS = ("to", "end", "endsat", "end_time", "endtime", "bis")
PRICE_FIELDS = (
    "price", "value", "total", "price_ct_per_kwh", "marketprice",
    "price_per_kwh", "preis", "wert",
)

_MINUTE = timedelta(minutes=1)


class PriceParseError(ValueError):
    """Antwort der Preisquelle ist nicht lesbar."""


@dataclass(frozen=True, slots=True)
class Slot:
    """Ein Preisintervall [start, end) in UTC mit Preis in ct/kWh."""

    start: datetime
    end: datetime
    price: float


# --------------------------------------------------------------------------
# Parsen
# --------------------------------------------------------------------------


def parse_payload(
    text: str,
    *,
    data_key: str | None = None,
    time_field: str | None = None,
    price_field: str | None = None,
    factor: float = 1.0,
    default_tz: tzinfo = timezone.utc,
) -> list[Slot]:
    """JSON- oder CSV-Antwort in sortierte Slots umwandeln."""
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped:
        raise PriceParseError("Leere Antwort")

    if stripped[0] in "[{":
        rows = _rows_from_json(stripped, data_key)
    else:
        rows = _rows_from_csv(stripped)
    if not rows:
        raise PriceParseError("Keine Datenzeilen gefunden")

    tkey = _pick(rows[0], time_field, TIME_FIELDS, "Zeit")
    pkey = _pick(rows[0], price_field, PRICE_FIELDS, "Preis")
    ekey = _find(rows[0], END_FIELDS)

    points: list[tuple[datetime, datetime | None, float]] = []
    for row in rows:
        start = parse_time(row.get(tkey), default_tz)
        price = parse_number(row.get(pkey))
        if start is None or price is None:
            continue
        end = parse_time(row.get(ekey), default_tz) if ekey else None
        points.append((start, end, price * factor))

    if not points:
        raise PriceParseError("Keine gültigen Zeilen (Zeit oder Preis nicht lesbar)")
    return build_slots(points)


def _rows_from_json(text: str, data_key: str | None) -> list[dict[str, Any]]:
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as err:
        raise PriceParseError(f"Ungültiges JSON: {err.msg}") from err

    if data_key:
        for part in data_key.split("."):
            try:
                data = data[int(part)] if isinstance(data, list) else data[part]
            except (KeyError, IndexError, ValueError, TypeError) as err:
                raise PriceParseError(f"Datenpfad '{data_key}' nicht gefunden") from err
    elif isinstance(data, dict):
        # Automatisch die erste Liste von Objekten suchen, z. B. {"data": [...]}
        data = next(
            (v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)),
            None,
        )

    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise PriceParseError("JSON enthält keine Liste von Objekten")
    return data


def _rows_from_csv(text: str) -> list[dict[str, Any]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [{(k or "").strip(): v for k, v in row.items()} for row in reader]
    if rows and len(rows[0]) < 2:
        raise PriceParseError("CSV hat weniger als zwei Spalten")
    return rows


def _find(row: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    lower = {k.lower(): k for k in row}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def _pick(row: dict[str, Any], wanted: str | None, candidates: tuple[str, ...], what: str) -> str:
    if wanted:
        lower = {k.lower(): k for k in row}
        if wanted.lower() in lower:
            return lower[wanted.lower()]
        raise PriceParseError(
            f"{what}-Feld '{wanted}' nicht vorhanden. Verfügbar: {', '.join(row)}"
        )
    found = _find(row, candidates)
    if found is None:
        raise PriceParseError(
            f"Kein {what}-Feld erkannt. Verfügbar: {', '.join(row)} – bitte manuell angeben"
        )
    return found


def parse_time(value: Any, default_tz: tzinfo = timezone.utc) -> datetime | None:
    """ISO-8601, Unix-Sekunden/-Millisekunden oder 'TT.MM.JJJJ HH:MM'."""
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        num = float(value)
        if num > 1e11:  # Millisekunden
            num /= 1000
        return datetime.fromtimestamp(num, tz=timezone.utc)

    text = str(value).strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        # Achtung: naive Zeiten sind in der Herbst-Umstellungsstunde mehrdeutig.
        # Quellen mit Offset (wie Spotty) haben dieses Problem nicht.
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(timezone.utc)


def parse_number(value: Any) -> float | None:
    """Zahl lesen, auch mit Dezimalkomma ('12,34') oder Tausenderpunkt."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def build_slots(points: list[tuple[datetime, datetime | None, float]]) -> list[Slot]:
    """Punkte sortieren, Duplikate entfernen, fehlende Enden ergänzen."""
    by_start: dict[datetime, tuple[datetime | None, float]] = {}
    for start, end, price in points:
        by_start[start] = (end, price)
    starts = sorted(by_start)

    diffs = [b - a for a, b in zip(starts, starts[1:]) if b > a]
    interval = median(diffs) if diffs else timedelta(minutes=15)

    slots: list[Slot] = []
    for i, start in enumerate(starts):
        end, price = by_start[start]
        if end is None or end <= start:
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            end = nxt if nxt is not None and nxt - start <= interval else start + interval
        slots.append(Slot(start, end, price))
    return slots


def merge_slots(old: list[Slot], new: list[Slot], keep_after: datetime) -> list[Slot]:
    """Neue Daten überschreiben alte; Veraltetes wird verworfen."""
    merged = {s.start: s for s in old if s.end > keep_after}
    for slot in new:
        merged[slot.start] = slot
    return [merged[k] for k in sorted(merged)]


# --------------------------------------------------------------------------
# Auswertung
# --------------------------------------------------------------------------


@dataclass(slots=True)
class CheapBlock:
    start: datetime
    end: datetime
    avg_price: float

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(slots=True)
class DeviceResult:
    start: datetime
    end: datetime
    cost_ct: float
    cost_now_ct: float | None
    saving_ct: float | None
    horizon_end: datetime
    deadline: datetime | None


@dataclass(slots=True)
class Snapshot:
    computed_at: datetime
    slots: list[Slot]
    current: Slot | None
    next: Slot | None
    today_min: Slot | None
    today_max: Slot | None
    threshold: float | None
    cheap_block: CheapBlock | None
    cheap_block_active: bool
    cheapest_now: bool
    forecast: list[dict[str, Any]]
    devices: dict[str, DeviceResult | None] = field(default_factory=dict)


def analyse(
    slots: list[Slot],
    now: datetime,
    tz: tzinfo,
    threshold_pct: float,
    devices: dict[str, tuple[list[float] | None, time | None]],
) -> Snapshot:
    """Alle Kennzahlen für einen Zeitpunkt berechnen."""
    slots = sorted(slots, key=lambda s: s.start)
    today = now.astimezone(tz).date()
    today_slots = [s for s in slots if s.start.astimezone(tz).date() == today]

    current = next((s for s in slots if s.start <= now < s.end), None)
    after = current.end if current else now
    nxt = next((s for s in slots if s.start >= after), None)

    today_min = min(today_slots, key=lambda s: s.price, default=None)
    today_max = max(today_slots, key=lambda s: s.price, default=None)

    threshold = percentile_threshold([s.price for s in today_slots], threshold_pct)
    block = longest_cheap_block(today_slots, threshold) if threshold is not None else None

    forecast = [
        {"datetime": s.start.astimezone(tz).isoformat(), "price": round(s.price, 2)}
        for s in slots
        if s.end > now
    ]

    results = {
        key: optimal_start(slots, watts, now, deadline=next_occurrence(finish_by, now, tz))
        if watts
        else None
        for key, (watts, finish_by) in devices.items()
    }

    return Snapshot(
        computed_at=now,
        slots=slots,
        current=current,
        next=nxt,
        today_min=today_min,
        today_max=today_max,
        threshold=threshold,
        cheap_block=block,
        cheap_block_active=bool(block and block.start <= now < block.end),
        cheapest_now=bool(current and today_min and current.start == today_min.start),
        forecast=forecast,
        devices=results,
    )


def percentile_threshold(prices: list[float], pct: float) -> float | None:
    """Preis, unter dem die günstigsten pct Prozent der Intervalle liegen."""
    if not prices:
        return None
    ordered = sorted(prices)
    idx = min(int(len(ordered) * pct / 100), len(ordered) - 1)
    return ordered[max(idx, 0)]


def longest_cheap_block(slots: list[Slot], threshold: float) -> CheapBlock | None:
    """Längster zusammenhängender Zeitraum unter der Schwelle.

    Bei Gleichstand gewinnt der mit dem niedrigeren Durchschnitt.
    Lücken in den Daten trennen Blöcke (anders als vorher, wo nur
    die Reihenfolge der API zählte).
    """
    best: list[Slot] = []
    run: list[Slot] = []

    def better(a: list[Slot], b: list[Slot]) -> bool:
        if len(a) != len(b):
            return len(a) > len(b)
        return bool(a) and sum(s.price for s in a) / len(a) < sum(s.price for s in b) / len(b)

    for slot in sorted(slots, key=lambda s: s.start):
        contiguous = run and run[-1].end == slot.start
        if slot.price <= threshold and (contiguous or not run):
            run.append(slot)
            continue
        if better(run, best):
            best = run
        run = [slot] if slot.price <= threshold else []
    if better(run, best):
        best = run

    if not best:
        return None
    return CheapBlock(best[0].start, best[-1].end, sum(s.price for s in best) / len(best))


# --------------------------------------------------------------------------
# Optimierung
# --------------------------------------------------------------------------


def ceil_minute(moment: datetime) -> datetime:
    floored = moment.replace(second=0, microsecond=0)
    return floored if floored == moment else floored + _MINUTE


def next_occurrence(at: time | None, now: datetime, tz: tzinfo) -> datetime | None:
    """Nächstes Auftreten einer lokalen Uhrzeit nach 'now' (für 'fertig bis')."""
    if at is None:
        return None
    local_now = now.astimezone(tz)
    day: date = local_now.date()
    candidate = datetime.combine(day, at, tzinfo=tz)
    if candidate <= local_now:
        candidate = datetime.combine(day + timedelta(days=1), at, tzinfo=tz)
    return candidate.astimezone(timezone.utc)


def optimal_start(
    slots: list[Slot],
    watts: list[float],
    now: datetime,
    *,
    deadline: datetime | None = None,
) -> DeviceResult | None:
    """Günstigste Startminute ab jetzt über ALLE bekannten Preise.

    Kein Schnitt an Mitternacht: ein Lauf 23:30–01:15 ist ein ganz
    normaler Kandidat. Kosten = Σ Leistung(Minute i) × Preis(Start + i).

    Da Preise je Slot konstant sind, wird pro Slot mit Präfixsummen
    des Profils gerechnet statt Minute für Minute – ~15× schneller.
    """
    length = len(watts)
    if length == 0:
        return None

    base = ceil_minute(now)
    runs: list[tuple[int, int, float]] = []  # (von_min, bis_min, Preis) relativ zu base
    cursor = base
    for slot in sorted(slots, key=lambda s: s.start):
        if slot.end <= base:
            continue
        if slot.start > cursor:
            break  # Datenlücke: ab hier kein verlässlicher Horizont
        a = int((max(slot.start, base) - base).total_seconds() // 60)
        b = int((slot.end - base).total_seconds() // 60)
        if b > a:
            runs.append((a, b, slot.price))
        cursor = slot.end
    if not runs:
        return None

    horizon = runs[-1][1]
    limit = horizon
    if deadline is not None:
        limit = min(limit, int((deadline - base).total_seconds() // 60))
    if length > limit:
        return None

    prefix = [0.0]
    for w in watts:
        prefix.append(prefix[-1] + w)

    best_t0 = 0
    best_cost: float | None = None
    cost_now: float | None = None
    first_run = 0
    for t0 in range(limit - length + 1):
        while runs[first_run][1] <= t0:
            first_run += 1
        t1 = t0 + length
        cost = 0.0
        i = first_run
        while i < len(runs) and runs[i][0] < t1:
            lo = max(runs[i][0], t0) - t0
            hi = min(runs[i][1], t1) - t0
            cost += runs[i][2] * (prefix[hi] - prefix[lo])
            i += 1
        if t0 == 0:
            cost_now = cost
        if best_cost is None or cost < best_cost - 1e-9:
            best_cost, best_t0 = cost, t0

    to_ct = 1 / 60000  # W·min × ct/kWh → ct
    start = base + best_t0 * _MINUTE
    best_ct = best_cost * to_ct  # type: ignore[operator]
    now_ct = cost_now * to_ct if cost_now is not None else None
    return DeviceResult(
        start=start,
        end=start + length * _MINUTE,
        cost_ct=best_ct,
        cost_now_ct=now_ct,
        saving_ct=(now_ct - best_ct) if now_ct is not None else None,
        horizon_end=base + horizon * _MINUTE,
        deadline=deadline,
    )
