"""
fetch_sncf.py
Récupère les arrêts des Intercités de Nuit SNCF via l'API SNCF Open Data.
Nécessite une clé API SNCF (gratuite) : data.sncf.com → "Mes tokens"
Passer via la variable d'environnement SNCF_API_KEY.
"""

import os
import requests
import time
from datetime import datetime, timedelta

SNCF_API_BASE = "https://api.sncf.com/v1/coverage/sncf"
REQUEST_DELAY = 1.5


def get_journey(from_station: str, to_station: str, train_number: str) -> dict | None:
    api_key = os.environ.get("SNCF_API_KEY")
    if not api_key:
        print("  ⚠️  SNCF_API_KEY manquant — arrêts SNCF conservés depuis routes.json")
        return None

    from_id = _find_station_id(from_station, api_key)
    to_id = _find_station_id(to_station, api_key)
    if not from_id or not to_id:
        return None

    for day_offset in range(1, 8):
        candidate = datetime.now() + timedelta(days=day_offset)
        dep = candidate.replace(hour=21, minute=0, second=0, microsecond=0)
        dep_str = dep.strftime("%Y%m%dT%H%M%S")

        try:
            time.sleep(REQUEST_DELAY)
            r = requests.get(
                f"{SNCF_API_BASE}/journeys",
                params={
                    "from": from_id,
                    "to": to_id,
                    "datetime": dep_str,
                    "count": 5,
                    "data_freshness": "realtime",
                },
                auth=(api_key, ""),
                timeout=15,
            )
            r.raise_for_status()
            journeys = r.json().get("journeys", [])

            for journey in journeys:
                sections = [s for s in journey.get("sections", []) if s.get("type") == "public_transport"]
                if len(sections) != 1:
                    continue
                section = sections[0]
                display_info = section.get("display_informations", {})
                headsign = display_info.get("headsign", "") or ""
                trip_name = display_info.get("trip_short_name", "") or ""

                tn_clean = train_number.replace(" ", "").lower()
                if tn_clean in headsign.lower() or tn_clean in trip_name.lower():
                    result = _extract_stops(section)
                    if result and len(result["stops"]) >= 2:
                        return result

        except Exception as e:
            print(f"  ⚠️  Erreur SNCF jour+{day_offset}: {e}")
            continue

    print(f"  ⚠️  Train SNCF {train_number} introuvable ({from_station} → {to_station})")
    return None


def _find_station_id(name: str, api_key: str) -> str | None:
    try:
        r = requests.get(
            f"{SNCF_API_BASE}/places",
            params={"q": name, "type[]": "stop_area", "count": 3},
            auth=(api_key, ""),
            timeout=10,
        )
        r.raise_for_status()
        places = r.json().get("places", [])
        if places:
            return places[0]["id"]
    except Exception as e:
        print(f"  ⚠️  Lookup SNCF {name}: {e}")
    return None


def _extract_stops(section: dict) -> dict | None:
    stops = []
    coords = []

    stop_times = section.get("stop_date_times", [])
    for i, st in enumerate(stop_times):
        stop_point = st.get("stop_point", {})
        coord = stop_point.get("coord", {})
        try:
            lat = float(coord.get("lat", 0))
            lon = float(coord.get("lon", 0))
        except (ValueError, TypeError):
            continue

        arr_str = st.get("arrival_date_time", "")
        dep_str = st.get("departure_date_time", "")
        arr = arr_str[9:11] + ":" + arr_str[11:13] if len(arr_str) >= 13 else None
        dep = dep_str[9:11] + ":" + dep_str[11:13] if len(dep_str) >= 13 else None

        # Premier stop : pas d'arrivée ; dernier stop : pas de départ
        if i == 0:
            arr = None
        if i == len(stop_times) - 1:
            dep = None

        coords.append({"lat": round(lat, 4), "lon": round(lon, 4)})
        stops.append({
            "city": stop_point.get("name", ""),
            "arrival": arr,
            "departure": dep,
        })

    return {"stops": stops, "coordinates": coords} if len(stops) >= 2 else None
