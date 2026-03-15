# nighttrain-data

Données des trains de nuit européens pour l'app **NightTrain** (iOS).

## Structure

```
routes.json          ← Source de vérité, fetchée par l'app iOS
scripts/
  update_routes.py   ← Script de mise à jour automatique
.github/workflows/
  update-routes.yml  ← GitHub Actions (chaque lundi 6h UTC)
```

## Mise à jour automatique

Le workflow GitHub Actions tourne chaque lundi et :
1. Interroge l'API Hafas (ÖBB/DB) pour les horaires Nightjet
2. Vérifie le statut via SNCF Open Data
3. Met à jour `routes.json` si des changements sont détectés
4. Commit automatiquement

## Mise à jour manuelle

Pour déclencher manuellement :
- GitHub → Actions → "Update routes.json" → Run workflow

Pour éditer directement :
- Modifier `routes.json` et push

## Connecter l'app iOS

Dans `DataService.swift`, remplacer `TON_GITHUB` par ton username :
```swift
private let remoteURL = "https://raw.githubusercontent.com/TON_GITHUB/nighttrain-data/main/routes.json"
```

## Schéma routes.json

```json
{
  "version": 1,
  "updated_at": "2026-03-15",
  "routes": [
    {
      "id": "nj-paris-berlin",
      "name": "Paris → Berlin",
      "operator": "Nightjet / SNCF",
      "status": "active",
      "operating_days": "Quotidien",
      "duration": "13h15",
      "is_direct": true,
      "bike_allowed": true,
      "pet_allowed": false,
      "meal_included": true,
      "shower_available": true,
      "booking_url": "https://www.nightjet.com",
      "coordinates": [{ "lat": 48.8566, "lon": 2.3522 }],
      "stops": [{ "city": "Paris Est", "arrival": null, "departure": "19:42" }],
      "accommodations": [{ "type": "seat", "startingPrice": 29 }]
    }
  ]
}
```
