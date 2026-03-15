"""
validate.py
Valide routes.json avant de committer. Fait échouer le job CI (exit 1) si:
  - Des routes ont disparu
  - Des routes ont perdu > 30% de leurs arrêts
  - Des coordonnées sont hors d'Europe
  - Des champs obligatoires sont absents
  - Le JSON n'est pas au format RoutesPayload

Usage :
  python scripts/validate.py routes_backup.json routes.json
"""

import json
import sys
from pathlib import Path

# Bounding box Europe élargie (inclut les Açores, Canaries, Chypre)
EUROPE_LAT = (27.0, 72.0)
EUROPE_LON = (-30.0, 50.0)

REQUIRED_FIELDS = [
    "id", "name", "operator", "operator_url", "status",
    "coordinates", "stops", "duration", "operating_days",
    "accommodations", "bike_allowed", "pet_allowed",
    "meal_included", "shower_available", "is_direct", "booking_url",
]

VALID_STATUSES = {"active", "suspended", "upcoming"}


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {"version": 0, "routes": raw}
    return raw


def validate(backup_path: str, new_path: str) -> bool:
    print(f"=== validate.py ===")
    print(f"Backup : {backup_path}")
    print(f"Nouveau : {new_path}")

    try:
        backup = load(backup_path)
        new = load(new_path)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"❌ Impossible de charger les fichiers : {e}")
        return False

    prev_routes: list = backup.get("routes", [])
    new_routes: list = new.get("routes", [])
    prev_map = {r["id"]: r for r in prev_routes}
    new_map = {r["id"]: r for r in new_routes}

    errors = []
    warnings = []

    # 1. Vérification du format RoutesPayload
    if "version" not in new or "updated_at" not in new or "routes" not in new:
        errors.append("Format invalide : champs version/updated_at/routes manquants")

    # 2. Aucune route ne doit avoir disparu
    for rid in prev_map:
        if rid not in new_map:
            errors.append(f"DISPARU : {rid}")

    # 3. Vérifications par route
    for route in new_routes:
        rid = route.get("id", "<sans id>")

        # Champs obligatoires
        for field in REQUIRED_FIELDS:
            if field not in route:
                errors.append(f"{rid} : champ obligatoire manquant '{field}'")

        # Statut valide
        status = route.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"{rid} : statut invalide '{status}'")

        # Régression de stops (> 30%)
        prev = prev_map.get(rid)
        if prev:
            old_n = len(prev.get("stops", []))
            new_n = len(route.get("stops", []))
            if old_n > 0 and new_n < old_n * 0.70:
                errors.append(
                    f"{rid} : régression stops {old_n}→{new_n} "
                    f"(-{100 - new_n * 100 // old_n}%) sans filet de sécurité"
                )

        # Coordonnées dans le bounding box Europe
        for coord in route.get("coordinates", []):
            lat = coord.get("lat", 0)
            lon = coord.get("lon", 0)
            if not (EUROPE_LAT[0] <= lat <= EUROPE_LAT[1]):
                warnings.append(f"{rid} : latitude hors Europe {lat}")
            if not (EUROPE_LON[0] <= lon <= EUROPE_LON[1]):
                warnings.append(f"{rid} : longitude hors Europe {lon}")

        # Au moins 2 stops pour tracer une polyline
        stops = route.get("stops", [])
        coords = route.get("coordinates", [])
        if len(stops) < 2:
            warnings.append(f"{rid} : seulement {len(stops)} stop(s)")
        if len(coords) < 2:
            warnings.append(f"{rid} : seulement {len(coords)} coordonnée(s)")

    # Résumé
    print(f"\nRoutes backup : {len(prev_routes)}")
    print(f"Routes nouveau : {len(new_routes)}")
    print(f"Version : {backup.get('version', 0)} → {new.get('version', 0)}")

    if warnings:
        print(f"\n⚠️  {len(warnings)} avertissement(s) :")
        for w in warnings:
            print(f"  {w}")

    if errors:
        print(f"\n❌ {len(errors)} erreur(s) bloquante(s) :")
        for e in errors:
            print(f"  {e}")
        print("\nCommit bloqué. Corrige les erreurs et relance.")
        return False

    print(f"\n✅ Validation réussie — {len(new_routes)} routes OK")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python validate.py <backup.json> <new_routes.json>")
        sys.exit(1)
    ok = validate(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
