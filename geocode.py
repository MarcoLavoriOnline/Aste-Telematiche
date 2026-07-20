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
from datetime import datetime

import requests

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
CACHE_PATH = Path(__file__).parent / "geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim richiede un User-Agent che identifichi l'applicazione,
# non il browser: e' un requisito della loro usage policy.
HEADERS = {
    "User-Agent": "aste-genova-personal-scraper (progetto personale, uso non commerciale, "
                  "github.com/MarcoLavoriOnline/Aste-Telematiche)"
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


def _geocodifica_query(query: str) -> dict | None:
    """Prova una singola query su Nominatim. Ritorna coords o None, loggando il motivo del fallimento."""
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "it",
    }
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f"  Nominatim ha risposto {resp.status_code} per '{query}': {resp.text[:200]}")
            return None
        risultati = resp.json()
        if risultati:
            return {"lat": float(risultati[0]["lat"]), "lon": float(risultati[0]["lon"])}
        log.info(f"  Nessun risultato per '{query}'")
    except Exception as e:
        log.warning(f"  Eccezione durante la geocodifica di '{query}': {e}")
    return None


def _geocodifica_indirizzo(indirizzo: str, comune: str) -> dict | None:
    """
    Prova prima l'indirizzo completo. Se non trova nulla, prova con il
    solo comune (posizione approssimata, ma meglio che niente sulla mappa).
    """
    if indirizzo:
        query_completa = f"{indirizzo}, {comune}, Italia"
        coords = _geocodifica_query(query_completa)
        if coords:
            coords["approssimato"] = False
            return coords
        time.sleep(1.1)

    if comune:
        query_comune = f"{comune}, Italia"
        coords = _geocodifica_query(query_comune)
        if coords:
            coords["approssimato"] = True
            return coords

    return None


def geocodifica_snapshot():
    snapshot = _latest_snapshot()
    cache = _load_cache()

    nuovi_geocodificati = 0
    trovati = 0
    non_trovati = 0
    falliti_dettaglio = []  # per il report leggibile

    for annuncio in snapshot["annunci"]:
        codice = annuncio["codice_asta"]
        if codice in cache:
            continue  # gia' geocodificato con successo in precedenza

        indirizzo = annuncio.get("indirizzo", "")
        comune = annuncio.get("comune", "")
        if not indirizzo and not comune:
            continue  # niente su cui basarsi, non ha senso nemmeno provare

        log.info(f"Geocodifico [{codice}]: '{indirizzo}' , '{comune}'")
        coords = _geocodifica_indirizzo(indirizzo, comune)
        nuovi_geocodificati += 1

        if coords:
            cache[codice] = coords
            trovati += 1
        else:
            non_trovati += 1
            falliti_dettaglio.append({
                "codice_asta": codice,
                "titolo": annuncio.get("titolo", ""),
                "indirizzo": indirizzo,
                "comune": comune,
            })
            # NON lo mettiamo in cache: cosi' viene ritentato al prossimo run,
            # nel caso il fallimento fosse dovuto a un blocco temporaneo del
            # servizio piuttosto che a un indirizzo davvero introvabile.

        time.sleep(1.1)  # rispettiamo il limite di Nominatim: max 1 richiesta al secondo

    _save_cache(cache)
    log.info(
        f"Geocodifica completata: {nuovi_geocodificati} indirizzi processati "
        f"({trovati} trovati, {non_trovati} non trovati/da ritentare), "
        f"{len(cache)} totali in cache."
    )

    _scrivi_report(snapshot, cache, falliti_dettaglio)


def _scrivi_report(snapshot: dict, cache: dict, falliti_questo_run: list):
    """
    Scrive un report leggibile (docs/report_geocodifica.txt) con l'elenco
    di TUTTI gli annunci del giorno che risultano senza coordinate, cosi'
    non serve scavare nei log di GitHub Actions per vederli.
    """
    tutti_senza_coordinate = []
    for a in snapshot["annunci"]:
        if a["codice_asta"] not in cache:
            tutti_senza_coordinate.append(a)

    righe = [
        f"Report geocodifica - generato il {datetime.now().isoformat()}",
        f"Totale annunci: {len(snapshot['annunci'])}",
        f"Geocodificati con successo: {len(snapshot['annunci']) - len(tutti_senza_coordinate)}",
        f"Senza coordinate: {len(tutti_senza_coordinate)}",
        f"(di cui falliti in QUESTO run, i restanti erano gia' falliti in run precedenti: {len(falliti_questo_run)})",
        "",
        "=" * 70,
        "ELENCO ANNUNCI SENZA COORDINATE:",
        "=" * 70,
        "",
    ]
    for a in tutti_senza_coordinate:
        righe.append(f"[{a['codice_asta']}] {a['titolo']}")
        righe.append(f"    Indirizzo: '{a.get('indirizzo', '')}'  |  Comune: '{a.get('comune', '')}'")
        righe.append("")

    OUTPUT_DIR = Path(__file__).parent / "docs"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report_geocodifica.txt").write_text("\n".join(righe), encoding="utf-8")


if __name__ == "__main__":
    geocodifica_snapshot()
