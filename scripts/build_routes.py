from __future__ import annotations
"""
build_routes.py
Script principal de mise à jour de routes.json.

Algorithme :
  1. Charge enrichment.yaml (config API par route)
  2. Charge routes.json existant (source de données actuelle)
  3. Pour chaque route, selon api: hafas_db | hafas_oebb | sncf | entur | manual :
       - Appelle l'API correspondante pour obtenir stops + coordonnées frais
       - Applique safe_stops() : si l'API renvoie moins de 70% des stops → garde le précédent
  4. Calcule le statut saisonnier (active_from / active_until)
  5. Calcule la durée automatiquement depuis les heures de départ/arrivée
  6. Émet routes.json au format RoutesPayload (version++, updated_at)

Usage :
  python scripts/build_routes.py
  python scripts/build_routes.py --dry-run   # affiche sans écrire
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

# ─── Chemins ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
ENRICHMENT_FILE = ROOT / "enrichment.yaml"
ROUTES_FILE = ROOT / "routes.json"

# ─── Imports des fetchers ────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))
from fetch_hafas import get_journey as hafas_journey
from fetch_entur import get_journey as entur_journey
from fetch_sncf import get_journey as sncf_journey


# ─── Statut saisonnier ───────────────────────────────────────────────────────

def resolve_status(base_status: str, seasonal: dict | None) -> str:
    """
    Calcule le statut effectif en tenant compte de la saison.
    Un statut 'suspended' ou 'upcoming' n'est jamais overridé.
    """
    if base_status in ("suspended", "upcoming"):
        return base_status
    if not seasonal:
        return base_status

    today = date.today()
    year = today.year
    try:
        d_from = date.fromisoformat(f"{year}-{seasonal['active_from']}")
        d_until = date.fromisoformat(f"{year}-{seasonal['active_until']}")
    except (KeyError, ValueError) as e:
        print(f"  ⚠️  Erreur format saisonnier: {e}")
        return base_status

    if d_from <= d_until:
        # Saison estivale (ex: 06-15 → 09-15)
        in_season = d_from <= today <= d_until
    else:
        # Saison hivernale croise le 1er janvier (ex: 12-01 → 03-20)
        in_season = today >= d_from or today <= d_until

    return "active" if in_season else "suspended"


# ─── Durée automatique ───────────────────────────────────────────────────────

def compute_duration(stops: list[dict]) -> str | None:
    """
    Calcule la durée totale depuis le départ du 1er stop jusqu'à l'arrivée du dernier.
    Gère le passage minuit. Retourne "~Xh" ou "~XhYY", None si données insuffisantes.
    """
    if not stops:
        return None
    dep_str = stops[0].get("departure")
    arr_str = stops[-1].get("arrival")
    if not dep_str or not arr_str:
        return None
    try:
        fmt = "%H:%M"
        dep = datetime.strptime(dep_str, fmt)
        arr = datetime.strptime(arr_str, fmt)
        if arr <= dep:
            arr += timedelta(days=1)
        delta = arr - dep
        total_min = delta.seconds // 60
        h, m = divmod(total_min, 60)
        return f"~{h}h" if m < 5 else f"~{h}h{m:02d}"
    except ValueError:
        return None


# ─── Filet de sécurité ───────────────────────────────────────────────────────

def safe_stops(route_id: str, new_stops: list, new_coords: list,
               prev_map: dict) -> tuple[list, list]:
    """
    Refuse la mise à jour si l'API renvoie moins de 70% des stops précédents.
    Préfère toujours conserver des données valides plutôt que des données dégradées.
    """
    prev = prev_map.get(route_id)
    if prev is None:
        return new_stops, new_coords  # nouvelle route

    prev_count = len(prev.get("stops", []))
    new_count = len(new_stops)

    if new_count == 0:
        print(f"  ↩  {route_id}: 0 stops API → conserve {prev_count} stops existants")
        return prev["stops"], prev["coordinates"]

    if prev_count > 0 and new_count < prev_count * 0.70:
        print(f"  ↩  {route_id}: régression {prev_count}→{new_count} stops → conserve existants")
        return prev["stops"], prev["coordinates"]

    return new_stops, new_coords


# ─── Enrichissement d'une route ──────────────────────────────────────────────

def enrich_route(route: dict, cfg: dict, prev_map: dict) -> dict:
    """
    Tente de récupérer des stops frais depuis l'API configurée.
    Applique le filet de sécurité et calcule le statut + durée.
    """
    route_id = route["id"]
    api = cfg.get("api", "manual")
    seasonal = cfg.get("seasonal")

    new_stops, new_coords = None, None

    if api != "manual":
        print(f"  → {route_id} [{api}]")
        try:
            if api in ("hafas_db", "hafas_oebb"):
                result = hafas_journey(
                    api,
                    cfg["from_station"],
                    cfg["to_station"],
                    cfg["train_number"],
                )
            elif api == "entur":
                result = entur_journey(
                    cfg["from_station"],
                    cfg["to_station"],
                    cfg["train_number"],
                )
            elif api == "sncf":
                result = sncf_journey(
                    cfg["from_station"],
                    cfg["to_station"],
                    cfg["train_number"],
                )
            else:
                result = None

            if result:
                new_stops = result["stops"]
                new_coords = result["coordinates"]
        except Exception as e:
            print(f"  ⚠️  Exception pour {route_id}: {e}")

    # Filet de sécurité
    if new_stops is not None:
        final_stops, final_coords = safe_stops(
            route_id, new_stops, new_coords, prev_map
        )
    else:
        # Pas d'enrichissement (manual ou échec) → garde l'existant
        final_stops = route.get("stops", [])
        final_coords = route.get("coordinates", [])

    # Calcul durée automatique (remplace "~11h" codé en dur si on a les données)
    computed_duration = compute_duration(final_stops)
    duration = computed_duration or route.get("duration", "")

    # Statut saisonnier
    effective_status = resolve_status(route["status"], seasonal)

    updated = dict(route)
    updated["stops"] = final_stops
    updated["coordinates"] = final_coords
    updated["duration"] = duration
    updated["status"] = effective_status

    return updated


# ─── Script principal ────────────────────────────────────────────────────────

def main(dry_run: bool = False):
    print("=== build_routes.py ===")
    print(f"Date : {date.today()}")

    # Charger enrichment.yaml
    enrichment_cfg: dict = {}
    if ENRICHMENT_FILE.exists():
        with open(ENRICHMENT_FILE, encoding="utf-8") as f:
            enrichment_cfg = yaml.safe_load(f).get("routes", {})
    else:
        print("⚠️  enrichment.yaml introuvable — tout sera conservé tel quel")

    # Charger routes.json existant
    prev_payload: dict = {"version": 0, "updated_at": "", "routes": []}
    if ROUTES_FILE.exists():
        with open(ROUTES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
            # Accepte les deux formats : RoutesPayload ou tableau brut
            if isinstance(raw, list):
                prev_payload["routes"] = raw
            else:
                prev_payload = raw

    prev_routes: list = prev_payload.get("routes", [])
    prev_map: dict = {r["id"]: r for r in prev_routes}

    print(f"Routes existantes : {len(prev_routes)}")

    # Enrichir chaque route
    updated_routes = []
    for route in prev_routes:
        route_id = route["id"]
        cfg = enrichment_cfg.get(route_id, {"api": "manual"})
        enriched = enrich_route(route, cfg, prev_map)
        updated_routes.append(enriched)

    # Construire le payload final
    new_version = prev_payload.get("version", 0) + 1
    new_payload = {
        "version": new_version,
        "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "routes": updated_routes,
    }

    print(f"\n✅ {len(updated_routes)} routes traitées")
    print(f"   Version : {prev_payload.get('version', 0)} → {new_version}")

    # Générer le message de commit descriptif
    _print_diff_summary(prev_map, updated_routes)

    if dry_run:
        print("\n[dry-run] routes.json non modifié")
        return

    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(new_payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 routes.json écrit ({ROUTES_FILE})")


def _print_diff_summary(prev_map: dict, updated_routes: list):
    """Affiche un résumé des changements pour le message de commit."""
    lines = []
    for route in updated_routes:
        rid = route["id"]
        prev = prev_map.get(rid)
        if prev is None:
            lines.append(f"Ajouté: {rid}")
            continue
        old_n = len(prev.get("stops", []))
        new_n = len(route.get("stops", []))
        if old_n != new_n:
            lines.append(f"Mis à jour: {rid} ({old_n}→{new_n} arrêts)")
        old_s = prev.get("status")
        new_s = route.get("status")
        if old_s != new_s:
            lines.append(f"Statut: {rid} {old_s}→{new_s}")

    if lines:
        print("\n--- Changements ---")
        for l in lines:
            print(f"  {l}")
    else:
        print("\n  Aucun changement détecté")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Ne pas écrire routes.json")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
