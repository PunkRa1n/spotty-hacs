# Spotty Strompreis-Optimierer

Home-Assistant-Integration für dynamische Stromtarife. Holt Viertelstundenpreise
von **Spotty** oder **jeder beliebigen URL, die JSON oder CSV liefert**, und
berechnet für deine Haushaltsgeräte den günstigsten Startzeitpunkt, gewichtet
mit dem echten Lastprofil des Geräts.

## Was sie kann

- Preis-Sensoren: aktuell, nächster, Minimum/Maximum heute, Schwelle,
  längster günstiger Zeitraum, Prognose (für die Plotly-Card)
- **Optimaler Start pro Gerät**: rechnet über alle bekannten Preise ab jetzt,
  auch über Mitternacht, optional mit „fertig bis“ (z. B. 07:00)
- Lastprofile werden **einmal gelernt und dauerhaft gespeichert**
  (`.storage/spotty.<id>`, landet in jedem Backup). Der Recorder darf danach
  gern purgen, das Profil bleibt minutengenau erhalten.
- Drei Wege zum Profil: live mitschneiden, aus dem Recorder-Verlauf oder aus
  einer CSV importieren

## Installation über HACS

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repos,
   Kategorie **Integration**
2. „Spotty Strompreis-Optimierer“ installieren, Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → *Spotty*

## Preisquelle

**Spotty:** Die komplette URL aus deinem Konto eintragen, z. B.
`https://i.spottyenergie.at/api/prices/CONSUMPTION/<dein-schlüssel>?timezone=at`.
Der Schlüssel in der URL ist ein Zugangsschlüssel: Er wird nicht geloggt und im
Diagnose-Download geschwärzt.

**Eigene URL:** JSON (Liste von Objekten, auch verschachtelt) oder CSV
(`,` `;` oder Tab, Dezimalkomma ok). Zeit- und Preisfeld werden automatisch
erkannt, sonst manuell angeben. Zeitformate: ISO 8601, Unix-Sekunden/-Millisekunden
oder `TT.MM.JJJJ HH:MM`. Mit dem **Umrechnungsfaktor** kommt alles in ct/kWh
(EUR/MWh → `0.1`, EUR/kWh → `100`).

> Zeiten ohne Zeitzonen-Angabe werden als lokale Zeit gelesen und sind in der
> Herbst-Umstellungsstunde mehrdeutig. Quellen mit Offset sind die bessere Wahl.

URL oder Token ändern: Integration → ⋮ → *Neu konfigurieren*. Geräte und Profile bleiben erhalten.

## Geräte und Lastprofile

Integration → *Konfigurieren* → *Gerät hinzufügen*: Name, Leistungssensor (W oder kW),
Standby-Grenze, Nachlaufzeit, optional „fertig bis“.

Für unterschiedliche Programme legst du einfach mehrere Geräte mit demselben
Sensor an („Geschirrspüler Eco“, „Geschirrspüler Intensiv“).

Profil lernen, eine der drei Varianten:

| Weg | Wann |
|---|---|
| Schalter **Profil einlernen** einschalten, dann Gerät starten | Neuer Lauf. Endet automatisch, wenn das Gerät die Nachlaufzeit lang unter Standby bleibt. Unabhängig vom Recorder. |
| Aktion `spotty.learn_from_history` | Ein Lauf der letzten Tage, solange der Recorder ihn noch hat (Standard: 10 Tage) |
| Aktion `spotty.import_profile` | HA-Verlaufsexport als CSV, z. B. deine alten AppDaemon-Musterdateien |

**Sicherung:** Die Profile liegen in `.storage` und sind damit im HA-Backup.
Zusätzlich enthält der Diagnose-Download der Integration alle Profile als JSON.

## Entities

Mit dem Namen „Spotty“ entstehen dieselben Entity-IDs wie früher unter AppDaemon,
z. B. `sensor.spotty_aktueller_strompreis` und `sensor.spotty_optimaler_<gerät>_start`.

Am optimalen Start hängen diese Attribute: `ende`, `kosten_ct`,
`kosten_bei_start_jetzt_ct`, `ersparnis_ct`, `preise_bekannt_bis`.

Beispiel: Gerät zum optimalen Zeitpunkt starten, aber nur wenn es sich lohnt.

```yaml
triggers:
  - trigger: time
    at: sensor.spotty_optimaler_geschirrspuler_start
conditions:
  - condition: template
    value_template: "{{ state_attr('sensor.spotty_optimaler_geschirrspuler_start', 'ersparnis_ct') | float(0) > 2 }}"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.geschirrspuler_steckdose
```

## Umstieg von AppDaemon

1. AppDaemon-Apps `strompreise` und `stromoptimierung` **deaktivieren**, sonst
   überschreiben sie per `set_state` die neuen Sensoren.
2. Integration mit Namen „Spotty“ einrichten, Geräte anlegen.
3. Alte Musterdateien nach `/config/spotty/` kopieren und importieren:
   ```yaml
   action: spotty.import_profile
   data:
     device_id: <Gerät auswählen>
     path: spotty/geschirrspueler.csv
   ```
4. Helfer `input_number.spotty_strompreis_schwelle_prozent` und
   `input_button.spotty_muster_neu_laden` löschen. Die Schwelle heißt jetzt
   `number.spotty_strompreis_schwelle_prozent`.

**Geändertes Verhalten:** `sensor.spotty_optimaler_<gerät>_start` zeigt jetzt den
*nächsten* optimalen Start ab jetzt statt des besten Zeitpunkts des Tages, der
schon vorbei sein konnte. Die `…_start_morgen`-Sensoren entfallen, weil die
Berechnung automatisch alle bekannten Preise einbezieht, sobald die Preise für
morgen da sind. Benachrichtigungen (Tagesbericht) gehören in eine Automation.

## Entwicklung

```bash
python -m pytest tests/     # Rechenlogik, läuft ohne Home Assistant
```
