#!/usr/bin/env python3
"""
NightTrain — Script de mise à jour automatique de routes.json
Interroge les APIs ferroviaires officielles et met à jour les données.

APIs utilisées :
- ÖBB Hafas (Nightjet) : https://v6.db.transport.rest/
- SNCF Open Data      : https://data.sncf.com/api/explore/v2.1/
"""

import json
import urllib.request
import urllib.parse
import sys
from datetime import datetime, timezone

ROUTES_FILE = "routes.json"
HAFAS_BASE  = "https://v6.db.transport.rest"
SNCF_BASE   = "https://data.sncf.com/api/explore/v2.1/catalog/datasets"

# ── Stations connues (Hafas station IDs) ────────────────────────────────────
STATIONS = {
    "Paris Est":           "8796066",
    "Paris Austerlitz":    "8775812",
    "Paris Nord":          "8727100",
    "Berlin Hbf":          "8011160",
    "Vienne Hbf":          "8100003",
    "Munich Hbf":          "8000261",
    "Amsterdam Centraal":  "8400058",
    "Zurich Hbf":          "8503000",
    "Rome Termini":        "8300091",
    "Hamburg Hbf":         "8002549",
    "Strasbourg":          "8706029",
    "Bruxelles Midi":      "8814001",
    "Frankfurt Hbf":       "8000105",
    "Barcelone Sants":     "8797002",
}

# ── Paires de routes Nightjet à vérifier ────────────────────────────────────
NIGHTJET_ROUTES = [
    ("Paris Est",          "Berlin Hbf",         "nj-paris-berlin"),
    ("Paris Est",          "Vienne Hbf",          "nj-paris-vienna"),
    ("Amsterdam Centraal", "Vienne Hbf",          "nj-amsterdam-vienna"),
    ("Zurich Hbf",         "Rome Termini",        "nj-zurich-rome"),
    ("Berlin Hbf",         "Vienne Hbf",          "nj-berlin-vienna"),
    ("Vienne Hbf",         "Hamburg Hbf",         "nj-vienna-hamburg"),
    ("Zurich Hbf",         "Vienne Hbf",          "nj-zurich-vienna"),
]


def fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NightTrainApp/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠️  Fetch failed: {url} — {e}")
        return None


def get_next_departure(from_id: str, to_id: str) -> dict | None:
    """Récupère le prochain départ Hafas entre deux gares."""
    params = urllib.parse.urlencode({
        "from":     from_id,
        "to":       to_id,
        "results":  1,
        "products": '{"nationalExpress":true}',
    })
    data = fetch_json(f"{HAFAS_BASE}/journeys?{params}")
    if not data or not data.get("journeys"):
        return None

    journey = data["journeys"][0]
    legs = journey.get("legs", [])
    if not legs:
        return None

    first_leg = legs[0]
    last_leg  = legs[-1]

    dep_time = first_leg.get("departure", "")
    arr_time = last_leg.get("arrival",   "")

    # Durée en minutes
    try:
        dep_dt  = datetime.fromisoformat(dep_time)
        arr_dt  = datetime.fromisoformat(arr_time)
        minutes = int((arr_dt - dep_dt).total_seconds() / 60)
        hours, mins = divmod(minutes, 60)
        duration = f"{hours}h{mins:02d}"
    except Exception:
        duration = None

    is_direct = len(legs) == 1

    return {
        "departure": dep_time[11:16] if len(dep_time) >= 16 else None,
        "arrival":   arr_time[11:16] if len(arr_time) >= 16 else None,
        "duration":  duration,
        "is_direct": is_direct,
    }


def update_route(route: dict, new_data: dict) -> bool:
    """Met à jour un route dict, retourne True si modifié."""
    changed = False

    if new_data.get("duration") and new_data["duration"] != route.get("duration"):
        print(f"  ↻ duration: {route.get('duration')} → {new_data['duration']}")
        route["duration"] = new_data["duration"]
        changed = True

    if new_data.get("is_direct") is not None and new_data["is_direct"] != route.get("is_direct"):
        print(f"  ↻ is_direct: {route.get('is_direct')} → {new_data['is_direct']}")
        route["is_direct"] = new_data["is_direct"]
        changed = True

    # Mise à jour heure départ 1er arrêt
    if new_data.get("departure") and route.get("stops"):
        first_stop = route["stops"][0]
        if first_stop.get("departure") != new_data["departure"]:
            print(f"  ↻ departure: {first_stop.get('departure')} → {new_data['departure']}")
            first_stop["departure"] = new_data["departure"]
            changed = True

    # Mise à jour heure arrivée dernier arrêt
    if new_data.get("arrival") and route.get("stops"):
        last_stop = route["stops"][-1]
        if last_stop.get("arrival") != new_data["arrival"]:
            print(f"  ↻ arrival: {last_stop.get('arrival')} → {new_data['arrival']}")
            last_stop["arrival"] = new_data["arrival"]
            changed = True

    return changed


def check_sncf_status() -> list[dict]:
    """
    Vérifie le statut des trains Intercités de Nuit via SNCF Open Data.
    Retourne une liste de {id, status}.
    """
    results = []
    dataset = "tgv-gares-et-voyageurs"  # À adapter selon le bon dataset SNCF
    url = f"{SNCF_BASE}/{dataset}/records?limit=1"
    data = fetch_json(url)
    if not data:
        print("  ⚠️  SNCF API non disponible")
    return results


def main():
    print(f"\n🚂 NightTrain — Mise à jour routes.json")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Charger le fichier existant
    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        print(f"❌ {ROUTES_FILE} introuvable")
        sys.exit(1)

    routes    = payload["routes"]
    route_map = {r["id"]: r for r in routes}
    total_changes = 0

    # ── Vérification Hafas (Nightjet) ─────────────────────────────────────
    print("📡 Interrogation Hafas API (Nightjet / DB)...")
    for from_name, to_name, route_id in NIGHTJET_ROUTES:
        if route_id not in route_map:
            print(f"  ⏭  {route_id} non trouvé dans routes.json, ignoré")
            continue

        from_id = STATIONS.get(from_name)
        to_id   = STATIONS.get(to_name)
        if not from_id or not to_id:
            print(f"  ⏭  Station ID manquant pour {from_name} ou {to_name}")
            continue

        print(f"  🔍 {from_name} → {to_name}")
        new_data = get_next_departure(from_id, to_id)
        if new_data:
            changed = update_route(route_map[route_id], new_data)
            if changed:
                total_changes += 1
                print(f"  ✅ {route_id} mis à jour")
            else:
                print(f"  ✓  {route_id} — pas de changement")
        else:
            print(f"  ⚠️  Pas de données Hafas pour {route_id}")

    # ── Mise à jour de la date ────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if payload.get("updated_at") != today:
        payload["updated_at"] = today
        total_changes += 1

    # ── Sauvegarde ────────────────────────────────────────────────────────
    if total_changes > 0:
        payload["routes"] = list(route_map.values())
        with open(ROUTES_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n✅ {total_changes} modification(s) sauvegardée(s) dans {ROUTES_FILE}")
    else:
        print(f"\n✓  Aucun changement détecté")

    print()


if __name__ == "__main__":
    main()
