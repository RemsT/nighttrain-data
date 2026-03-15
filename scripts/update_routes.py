#!/usr/bin/env python3
"""
NightTrain — Script de mise à jour automatique de routes.json
Scrappe les sources accessibles recensées dans le rapport de mars 2026.

Sources :
  - nightride.com         (changements horaires, nouvelles lignes)
  - back-on-track.eu      (base de données statuts)
  - eurail.com            (routes Nightjet officielles)
  - raileurope.com        (prix)
  - trainline.com         (routes ICN Italie)
"""

import json
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime, timezone
import sys
import re

ROUTES_FILE = "routes.json"

SOURCES = {
    "nightride_changes":   "https://nightride.com/en/blog/night-train-2026-heres-what-changes-in-the-new-timetable",
    "nightride_es":        "https://nightride.com/en/blog/european-sleeper-complete-guide",
    "back_on_track_db":    "https://back-on-track.eu/night-train-database/",
    "back_on_track_map":   "https://back-on-track.eu/night-train-map/",
    "eurail_nightjet":     "https://www.eurail.com/en/plan-your-trip/trip-ideas/trains-europe/night-trains/obb-nightjet",
    "eurail_all":          "https://www.eurail.com/en/plan-your-trip/trip-ideas/trains-europe/night-trains",
    "rail_europe_nj":      "https://www.raileurope.com/en-us/trains/nightjet",
    "rail_europe_icn":     "https://www.raileurope.com/en/trains/intercity-notte",
    "trainline_icn":       "https://www.thetrainline.com/trains/italy/night-trains",
    "seat61_icn":          "https://www.seat61.com/trains-and-routes/trenitalia-intercity-notte.htm",
    "thetraveler":         "https://www.thetraveler.org/europe-night-trains-2025-2026-new-routes-network-guide/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Mots-clés indiquant une suspension
SUSPENSION_KEYWORDS = [
    "cancelled", "suspended", "discontinued", "no longer", "stopped",
    "supprimé", "suspendu", "arrêté", "suppression",
]

# Mots-clés indiquant un lancement
LAUNCH_KEYWORDS = [
    "new route", "launched", "launches", "opening", "starts", "from march",
    "from april", "from december", "from january", "nouvelle ligne", "lancé",
]

# ── Utilitaires ──────────────────────────────────────────────────────────────

class TextExtractor(HTMLParser):
    """Extrait le texte brut d'une page HTML."""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)

    def get_text(self):
        return " ".join(self.text_parts)


def fetch_page(url: str, label: str) -> str | None:
    """Télécharge une page et retourne le texte brut."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            parser = TextExtractor()
            parser.feed(html)
            text = parser.get_text()
            print(f"  ✅ {label} ({len(text)} chars)")
            return text
    except urllib.error.HTTPError as e:
        print(f"  ❌ {label} — HTTP {e.code}")
    except Exception as e:
        print(f"  ❌ {label} — {e}")
    return None


def find_route_mentions(text: str, route_names: list[str]) -> dict[str, list[str]]:
    """
    Cherche les mentions d'un trajet dans un texte.
    Retourne {route_name: [phrases contenant ce trajet]}.
    """
    results = {}
    sentences = re.split(r'[.!?\n]', text)
    for route in route_names:
        hits = [s.strip() for s in sentences if route.lower() in s.lower() and len(s.strip()) > 20]
        if hits:
            results[route] = hits[:3]  # max 3 phrases
    return results


def detect_status_change(sentences: list[str]) -> str | None:
    """
    Analyse des phrases pour détecter un changement de statut.
    Retourne 'suspended', 'active', ou None.
    """
    text = " ".join(sentences).lower()
    for kw in SUSPENSION_KEYWORDS:
        if kw in text:
            return "suspended"
    for kw in LAUNCH_KEYWORDS:
        if kw in text:
            return "active"
    return None


# ── Analyse par source ────────────────────────────────────────────────────────

def analyze_nightride(text: str, route_map: dict) -> int:
    """Parse nightride.com pour détecter les changements de statut."""
    changes = 0
    route_search_names = {
        "Paris Berlin":     ["nj-paris-berlin", "es-paris-berlin"],
        "Paris Vienna":     ["nj-paris-vienna"],
        "Paris Wien":       ["nj-paris-vienna"],
        "Amsterdam Vienna": ["nj-amsterdam-vienna"],
        "Zurich Rome":      ["nj-zurich-rome"],
        "European Sleeper": ["es-paris-berlin"],
        "PKP Carpatia":     ["pkp-carpatia"],
        "Caledonian":       ["cal-london-edinburgh"],
        "SBB":              ["sbb-basel-copenhagen"],
    }

    for search_name, route_ids in route_search_names.items():
        mentions = find_route_mentions(text, [search_name])
        if not mentions:
            continue
        sentences = mentions.get(search_name, [])
        new_status = detect_status_change(sentences)
        if new_status:
            for route_id in route_ids:
                if route_id in route_map:
                    current = route_map[route_id].get("status")
                    if current != new_status:
                        print(f"  ↻ [{route_id}] status: {current} → {new_status}")
                        print(f"    Source: \"{sentences[0][:100]}...\"")
                        route_map[route_id]["status"] = new_status
                        changes += 1
    return changes


def analyze_eurail(text: str, route_map: dict) -> int:
    """Vérifie la présence des routes Nightjet sur Eurail."""
    changes = 0
    nightjet_routes = {
        "nj-amsterdam-vienna": "Amsterdam",
        "nj-zurich-rome":      "Zurich",
        "nj-berlin-vienna":    "Berlin Vienna",
        "nj-vienna-hamburg":   "Hamburg",
    }
    for route_id, keyword in nightjet_routes.items():
        if route_id not in route_map:
            continue
        if keyword.lower() in text.lower():
            if route_map[route_id].get("status") == "suspended":
                print(f"  ↻ [{route_id}] toujours mentionné sur Eurail → probablement actif")
                route_map[route_id]["status"] = "active"
                changes += 1
    return changes


def analyze_back_on_track(text: str, route_map: dict) -> int:
    """Parse Back-on-Track pour les statuts de lignes."""
    changes = 0
    status_map = {
        "operational": "active",
        "planned":     "upcoming",
        "suspended":   "suspended",
        "cancelled":   "suspended",
    }
    for keyword, status in status_map.items():
        if keyword not in text.lower():
            continue
        context = text.lower()
        idx = context.find(keyword)
        snippet = text[max(0, idx-100):idx+100]
        # Cherche un nom de ligne proche
        for route_id, route in route_map.items():
            city_pairs = route["name"].split(" → ")
            if len(city_pairs) == 2:
                from_city = city_pairs[0].split()[0]  # Premier mot de la ville départ
                if from_city.lower() in snippet.lower():
                    current = route.get("status")
                    if current != status:
                        print(f"  ↻ [{route_id}] Back-on-Track: {current} → {status}")
                        route["status"] = status
                        changes += 1
    return changes


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    print(f"\n🚂 NightTrain — Mise à jour routes.json")
    print(f"   {now.strftime('%Y-%m-%d %H:%M UTC')}\n")

    # Chargement
    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        print(f"❌ {ROUTES_FILE} introuvable")
        sys.exit(1)

    route_map = {r["id"]: r for r in payload["routes"]}
    total_changes = 0

    # ── Scraping ──────────────────────────────────────────────────────────

    print("📡 Scraping des sources...")

    pages = {}
    for key, url in SOURCES.items():
        label = key.replace("_", " ")
        text = fetch_page(url, label)
        if text:
            pages[key] = text

    print(f"\n📊 {len(pages)}/{len(SOURCES)} sources récupérées\n")

    # ── Analyse ───────────────────────────────────────────────────────────

    print("🔍 Analyse des changements...\n")

    if "nightride_changes" in pages:
        print("  → nightride.com (changements 2026)")
        total_changes += analyze_nightride(pages["nightride_changes"], route_map)

    if "nightride_es" in pages:
        print("  → nightride.com (European Sleeper)")
        total_changes += analyze_nightride(pages["nightride_es"], route_map)

    if "back_on_track_db" in pages:
        print("  → back-on-track.eu (base de données)")
        total_changes += analyze_back_on_track(pages["back_on_track_db"], route_map)

    if "eurail_nightjet" in pages:
        print("  → eurail.com (Nightjet)")
        total_changes += analyze_eurail(pages["eurail_nightjet"], route_map)

    if "eurail_all" in pages:
        print("  → eurail.com (tous trains de nuit)")
        total_changes += analyze_nightride(pages["eurail_all"], route_map)

    if "thetraveler" in pages:
        print("  → thetraveler.org (guide 2025-2026)")
        total_changes += analyze_nightride(pages["thetraveler"], route_map)

    # ── Rapport de ce qui a été trouvé ───────────────────────────────────

    print("\n📋 Rapport sources :")
    for key, text in pages.items():
        url = SOURCES[key]
        words = len(text.split())
        print(f"  {key:30s} {words:6d} mots — {url}")

    # ── Mise à jour date ──────────────────────────────────────────────────

    today = now.strftime("%Y-%m-%d")
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
        print(f"\n✓  Aucun changement détecté — {ROUTES_FILE} inchangé")

    print()


if __name__ == "__main__":
    main()
