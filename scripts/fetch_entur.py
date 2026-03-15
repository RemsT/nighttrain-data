"""
fetch_entur.py
Récupère les arrêts des trains de nuit norvégiens via l'API Entur (GraphQL).
Entur est l'API officielle du système ferroviaire norvégien (Vy, SJ Norge, Go-Ahead).
"""

import requests
import time
from datetime import datetime, timedelta

ENTUR_GRAPHQL = "https://api.entur.io/journey-planner/v3/graphql"
ENTUR_HEADERS = {
    "ET-Client-Name": "nighttrain-app-updater",
    "Content-Type": "application/json",
}

REQUEST_DELAY = 1.5


def get_journey(from_station: str, to_station: str, train_number: str) -> dict | None:
    """
    Cherche un trajet nocturne sur Entur GraphQL.
    Retourne {"stops": [...], "coordinates": [...]} ou None.
    """
    # Cherche sur les 7 prochains jours
    for day_offset in range(1, 8):
        candidate = datetime.now() + timedelta(days=day_offset)
        dep = candidate.replace(hour=20, minute=0, second=0, microsecond=0)

        query = """
        {
          trip(
            from: { name: "%s" }
            to:   { name: "%s" }
            dateTime: "%s"
            numTripPatterns: 5
            transportModes: [{transportMode: rail}]
          ) {
            tripPatterns {
              legs {
                line { publicCode }
                fromPlace { name }
                toPlace { name }
                expectedStartTime
                expectedEndTime
                intermediateEstimatedCalls {
                  quay {
                    name
                    coordinates { latitude longitude }
                  }
                  expectedArrivalTime
                  expectedDepartureTime
                }
                fromEstimatedCall {
                  quay { name coordinates { latitude longitude } }
                  expectedDepartureTime
                }
                toEstimatedCall {
                  quay { name coordinates { latitude longitude } }
                  expectedArrivalTime
                }
              }
            }
          }
        }
        """ % (from_station, to_station, dep.strftime("%Y-%m-%dT%H:%M:%S"))

        try:
            time.sleep(REQUEST_DELAY)
            r = requests.post(
                ENTUR_GRAPHQL,
                json={"query": query},
                headers=ENTUR_HEADERS,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            patterns = data.get("data", {}).get("trip", {}).get("tripPatterns", [])

            for pattern in patterns:
                for leg in pattern.get("legs", []):
                    line_code = leg.get("line", {}).get("publicCode", "") or ""
                    tn_clean = train_number.replace(" ", "").lower()
                    if tn_clean not in line_code.replace(" ", "").lower():
                        continue

                    result = _extract_stops(leg)
                    if result and len(result["stops"]) >= 2:
                        return result

        except Exception as e:
            print(f"  ⚠️  Erreur Entur jour+{day_offset}: {e}")
            continue

    print(f"  ⚠️  Train {train_number} introuvable sur Entur ({from_station} → {to_station})")
    return None


def _extract_stops(leg: dict) -> dict | None:
    stops = []
    coords = []

    # Premier arrêt
    from_call = leg.get("fromEstimatedCall", {})
    _append_stop(stops, coords, from_call["quay"], None, from_call.get("expectedDepartureTime"))

    # Arrêts intermédiaires
    for call in leg.get("intermediateEstimatedCalls", []):
        _append_stop(
            stops, coords, call["quay"],
            call.get("expectedArrivalTime"),
            call.get("expectedDepartureTime"),
        )

    # Dernier arrêt
    to_call = leg.get("toEstimatedCall", {})
    _append_stop(stops, coords, to_call["quay"], to_call.get("expectedArrivalTime"), None)

    if len(stops) < 2:
        return None
    return {"stops": stops, "coordinates": coords}


def _append_stop(stops, coords, quay, arr_iso, dep_iso):
    c = quay.get("coordinates", {})
    lat = c.get("latitude")
    lon = c.get("longitude")
    if lat is None or lon is None:
        return
    coords.append({"lat": round(lat, 4), "lon": round(lon, 4)})
    stops.append({
        "city": quay.get("name", ""),
        "arrival": _fmt(arr_iso),
        "departure": _fmt(dep_iso),
    })


def _fmt(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return iso[11:16]
    except Exception:
        return None
