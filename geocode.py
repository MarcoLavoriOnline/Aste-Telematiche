"""
Geocodifica gli indirizzi degli annunci (indirizzo + comune -> lat/lon)
usando Nominatim (OpenStreetMap), che e' gratuito e non richiede
chiave API.

Usa una cache persistente (geocode_cache.json, salvata nel repository)
per non dover geocodificare da capo ogni giorno: solo gli annunci
NUOVI vengono interrogati. Questo rispetta anche la policy d'uso di
Nominatim (max 1 richiesta al secondo, identificarsi con uno User-Agent
significativo) - ogni run tipicamente geocodifica solo una manciata di
indirizzi nuovi, non centinaia.

Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
"""
import json
import time
import logging
from pathlib import Path

import requests

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
CACHE_PATH = Path(__file__).parent / "geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim richiede un User-Agent che identifichi l'applicazione,
# non il browser: e' un requisito della loro usage policy.
HEADERS = {
    "User-Agent": "aste-genova-personal-scraper/1.0 (uso personale, non commerciale)"
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("geocode")


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_snapshot() -> dict:
    files = sorted(SNAPSHOT_DIR.glob("snapshot_*.json"))
    if not files:
        raise FileNotFoundError("Nessuno snapshot trovato in snapshots/")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _geocodifica_indirizzo(indirizzo: str, comune: str) -> dict | None:
    """Ritorna {'lat': ..., 'lon': ...} oppure None se non trovato."""
    query = f"{indirizzo}, {comune}, Italia"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "it",
    }
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        risultati = resp.json()
        if risultati:
            return {"lat": float(risultati[0]["lat"]), "lon": float(risultati[0]["lon"])}
    except Exception as e:
        log.warning(f"Errore geocodifica per '{query}': {e}")
    return None


def geocodifica_snapshot():
    snapshot = _latest_snapshot()
    cache = _load_cache()

    nuovi_geocodificati = 0
    for annuncio in snapshot["annunci"]:
        codice = annuncio["codice_asta"]
        if codice in cache:
            continue  # gia' in cache, non serve richiamare il servizio

        indirizzo = annuncio.get("indirizzo", "")
        comune = annuncio.get("comune", "")
        if not indirizzo and not comune:
            cache[codice] = None
            continue

        log.info(f"Geocodifico [{codice}]: {indirizzo}, {comune}")
        coords = _geocodifica_indirizzo(indirizzo, comune)
        cache[codice] = coords
        nuovi_geocodificati += 1

        # Rispettiamo il limite di Nominatim: max 1 richiesta al secondo
        time.sleep(1.1)

    _save_cache(cache)
    log.info(f"Geocodifica completata: {nuovi_geocodificati} nuovi indirizzi processati, "
              f"{len(cache)} totali in cache.")


if __name__ == "__main__":
    geocodifica_snapshot()
