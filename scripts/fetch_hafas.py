from __future__ import annotations
"""
fetch_hafas.py
Récupère les arrêts et coordonnées d'un train de nuit via l'API Hafas.

Profils disponibles :
  - hafas_db   : DB (Deutsche Bahn) — couvre DE/AT/CH/NL/BE/CZ/PL/DK/SE/HU/HR
  - hafas_oebb : ÖBB — couvre AT + IT (Roma, Milano, Venezia)

Usage (depuis build_routes.py) :
  from fetch_hafas import get_journey
  result = get_journey("hafas_db", "Wien Hbf", "Hamburg Hbf", "NJ 466")
  # → {"stops": [...], "coordinates": [...]} ou None si introuvable
"""

import requests
import time
from datetime import datetime, timedelta

# ─── Profils Hafas ──────────────────────────────────────────────────────────

PROFILES = {
    "hafas_db": {
        "base": "https://v6.db.transport.rest",
        "name": "DB Hafas",
    },
    "hafas_oebb": {
        "base": "https://v5.db.transport.rest",   # fallback sur DB si ÖBB indisponible
        "name": "ÖBB/DB Hafas",
    },
}

# Limite de requêtes : pause entre chaque appel pour éviter le rate-limit
REQUEST_DELAY = 1.2  # secondes

# Cache des EVA codes en mémoire pour éviter les doublons de lookup
_station_cache: dict[str, str] = {}


# ─── Lookup de station ──────────────────────────────────────────────────────

def find_station_id(base_url: str, station_name: str) -> str | None:
    """
    Cherche l'identifiant Hafas (EVA code) d'une gare par son nom.
    Retourne l'ID ou None si introuvable.
    """
    cache_key = f"{base_url}:{station_name}"
    if cache_key in _station_cache:
        return _station_cache[cache_key]

    try:
        r = requests.get(
            f"{base_url}/locations",
            params={"query": station_name, "results": 3, "stops": "true", "addresses": "false"},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json()
        if not results:
            print(f"  ⚠️  Station introuvable : {station_name}")
            return None
        station_id = results[0]["id"]
        _station_cache[cache_key] = station_id
        return station_id
    except Exception as e:
        print(f"  ⚠️  Erreur lookup {station_name}: {e}")
        return None


# ─── Récupération d'un trajet ───────────────────────────────────────────────

def get_journey(
    profile: str,
    from_station: str,
    to_station: str,
    train_number: str,
    search_days: int = 14,
) -> dict | None:
    """
    Cherche le prochain départ nocturne correspondant au train_number
    entre from_station et to_station.

    Retourne {"stops": [...], "coordinates": [...]} ou None.
    """
    base = PROFILES.get(profile, PROFILES["hafas_db"])["base"]

    from_id = find_station_id(base, from_station)
    to_id = find_station_id(base, to_station)
    if not from_id or not to_id:
        return None

    # Cherche sur les N prochains jours pour trouver un départ valide
    for day_offset in range(1, search_days + 1):
        candidate = datetime.now() + timedelta(days=day_offset)
        # Départ à 18h00 pour cibler les trains de nuit
        dep = candidate.replace(hour=18, minute=0, second=0, microsecond=0)

        try:
            time.sleep(REQUEST_DELAY)
            r = requests.get(
                f"{base}/journeys",
                params={
                    "from": from_id,
                    "to": to_id,
                    "departure": dep.isoformat(),
                    "results": 10,
                    # Exclure les transports urbains et courte distance
                    "bus": "false",
                    "subway": "false",
                    "tram": "false",
                    "taxi": "false",
                },
                timeout=15,
            )
            r.raise_for_status()
            journeys = r.json().get("journeys", [])

            for journey in journeys:
                legs = journey.get("legs", [])
                if len(legs) != 1:
                    continue  # On veut les trajets directs (1 seul leg)
                leg = legs[0]
                line_name = leg.get("line", {}).get("name", "") or ""
                fahrt_name = leg.get("fahrtNr", "") or ""

                # Filtre par numéro de train (partiel, insensible à la casse)
                tn_clean = train_number.replace(" ", "").lower()
                if tn_clean in line_name.replace(" ", "").lower() or \
                   tn_clean in fahrt_name.replace(" ", "").lower():
                    result = _extract_stops(leg)
                    if result and len(result["stops"]) >= 2:
                        return result

        except Exception as e:
            print(f"  ⚠️  Erreur Hafas jour+{day_offset}: {e}")
            continue

    print(f"  ⚠️  Train {train_number} introuvable ({from_station} → {to_station})")
    return None


def _extract_stops(leg: dict) -> dict | None:
    """Extrait la liste des arrêts et coordonnées depuis un leg Hafas."""
    stops = []
    coords = []

    stopovers = leg.get("stopovers", [])
    if not stopovers:
        return None

    for s in stopovers:
        stop_info = s.get("stop", {})
        location = stop_info.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")

        if lat is None or lon is None:
            continue

        # Formater les heures HH:MM (tronquer les secondes et timezone)
        arr_raw = s.get("arrival") or s.get("plannedArrival")
        dep_raw = s.get("departure") or s.get("plannedDeparture")
        arr = _format_time(arr_raw)
        dep = _format_time(dep_raw)

        coords.append({"lat": round(lat, 4), "lon": round(lon, 4)})
        stops.append({
            "city": stop_info.get("name", ""),
            "arrival": arr,
            "departure": dep,
        })

    # Nettoyer : premier stop sans arrivée, dernier sans départ
    if stops:
        stops[0]["arrival"] = None
        stops[-1]["departure"] = None

    return {"stops": stops, "coordinates": coords}


def _format_time(iso_str: str | None) -> str | None:
    """Convertit '2026-04-07T22:35:00+02:00' → '22:35'"""
    if not iso_str:
        return None
    try:
        # Prend uniquement HH:MM depuis la chaîne ISO (évite les dépendances dateutil)
        time_part = iso_str[11:16]
        if len(time_part) == 5 and ":" in time_part:
            return time_part
    except Exception:
        pass
    return None
