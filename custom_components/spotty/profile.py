"""Lastprofile aus Leistungsmesswerten bauen.

Reines Python ohne Home-Assistant-Importe.
Ein Profil ist eine Liste mittlerer Leistungen in W, eine pro Minute.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime

from .pricing import parse_number, parse_time

Sample = tuple[datetime, float]


def build_profile(
    samples: list[Sample],
    standby_w: float,
    end: datetime | None = None,
) -> list[float] | None:
    """Zeitgewichtetes Minutenprofil, auf den aktiven Bereich zugeschnitten.

    Ein Messwert gilt, bis der nächste kommt. Das ist korrekt für Sensoren,
    die nur bei Änderung melden – die alte Variante (Mittelwert pro Minute,
    leere Minuten = 0 W) hätte dort Leistung unterschlagen.
    """
    pts = sorted((t, v) for t, v in samples if v is not None)
    if not pts:
        return None

    origin = pts[0][0].replace(second=0, microsecond=0)
    stop = end if end is not None and end > pts[-1][0] else pts[-1][0]
    total = math.ceil((stop - origin).total_seconds() / 60)
    if total <= 0:
        return None

    energy = [0.0] * total
    covered = [0.0] * total
    for i, (t, value) in enumerate(pts):
        seg_end = pts[i + 1][0] if i + 1 < len(pts) else stop
        a = (t - origin).total_seconds()
        b = (seg_end - origin).total_seconds()
        while a < b:
            minute = int(a // 60)
            if minute >= total:
                break
            chunk = min(b, (minute + 1) * 60) - a
            energy[minute] += value * chunk
            covered[minute] += chunk
            a += chunk

    watts = [e / c if c > 0 else 0.0 for e, c in zip(energy, covered)]
    active = [i for i, w in enumerate(watts) if w > standby_w]
    if not active:
        return None
    return [round(w, 1) for w in watts[active[0] : active[-1] + 1]]


def parse_history_csv(text: str) -> list[Sample]:
    """HA-Verlaufsexport lesen (Spalten: entity_id,state,last_changed)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames or not {"state", "last_changed"} <= {
        f.strip() for f in reader.fieldnames
    }:
        raise ValueError("CSV braucht die Spalten 'state' und 'last_changed'")
    samples: list[Sample] = []
    for row in reader:
        t = parse_time(row.get("last_changed"))
        v = parse_number(row.get("state"))
        if t is not None and v is not None:
            samples.append((t, v))
    return samples


def energy_kwh(watts: list[float]) -> float:
    return sum(watts) / 60000


def clamp_start(samples: list[Sample], start: datetime) -> list[Sample]:
    """Werte vor 'start' auf 'start' ziehen (Recorder liefert den Anfangszustand
    mit seinem ursprünglichen Zeitstempel, der Tage zurückliegen kann)."""
    return [(max(t, start), v) for t, v in samples]

