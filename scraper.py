"""
Scraper per le aste immobiliari del Tribunale di Genova
(sito realizzato da Aste Giudiziarie Inlinea S.p.A.)

Il sito e' un ASP.NET WebForms classico: la paginazione avviene via
postback (__doPostBack), NON via link statici o API JSON. Ogni richiesta
successiva deve portarsi dietro il __VIEWSTATE / __VIEWSTATEGENERATOR
della pagina precedente, esattamente come farebbe un browser reale
quando "clicchi" un numero di pagina.

Non serve un browser headless: bastano requests + BeautifulSoup.
"""

import re
import json
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.tribunale.genova.it/venditegiudiziarie/default.aspx?m=1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("aste-scraper")


@dataclass
class Annuncio:
    codice_asta: str
    titolo: str
    indirizzo: str
    comune: str
    categoria: str
    ruolo: str
    anno: Optional[str]
    tipo_vendita: str
    lotto: str
    prezzo_base: str
    descrizione: str
    link: str
    stato: str  # "gara da iniziare" / "in corso o conclusa" / sconosciuto


class TribunaleGenovaScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._viewstate = None
        self._viewstategenerator = None
        self._eventvalidation = None

    # ------------------------------------------------------------------
    # Gestione ASP.NET postback state
    # ------------------------------------------------------------------
    def _extract_state(self, soup: BeautifulSoup):
        def val(id_):
            tag = soup.find("input", {"id": id_})
            return tag["value"] if tag and tag.has_attr("value") else None

        self._viewstate = val("__VIEWSTATE")
        self._viewstategenerator = val("__VIEWSTATEGENERATOR")
        self._eventvalidation = val("__EVENTVALIDATION")  # potrebbe non esserci

    def _base_payload(self):
        payload = {
            "__VIEWSTATE": self._viewstate or "",
            "__VIEWSTATEGENERATOR": self._viewstategenerator or "",
        }
        if self._eventvalidation:
            payload["__EVENTVALIDATION"] = self._eventvalidation
        return payload

    # ------------------------------------------------------------------
    # Caricamento pagine
    # ------------------------------------------------------------------
    def load_first_page(self) -> BeautifulSoup:
        log.info("GET pagina di ricerca (pagina 1)")
        resp = self.session.get(BASE_URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        self._extract_state(soup)
        return soup

    def load_page(self, page_number: int) -> BeautifulSoup:
        """
        Simula il click sul bottone di paginazione numero `page_number`.
        Il control id segue il pattern:
        ctl00$mainc$PrimaSel$lnk_btn_valore_<N>
        """
        target = f"ctl00$mainc$PrimaSel$lnk_btn_valore_{page_number}"
        payload = self._base_payload()
        payload.update({
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": "",
        })
        log.info(f"POST pagina {page_number}")
        resp = self.session.post(BASE_URL, data=payload, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        self._extract_state(soup)
        return soup

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _total_pages(soup: BeautifulSoup) -> int:
        div = soup.find("div", class_="paginazione_pagina_di")
        if not div:
            return 1
        m = re.search(r"Pagina \d+ di (\d+) pagine", div.get_text())
        return int(m.group(1)) if m else 1

    @staticmethod
    def _total_results(soup: BeautifulSoup) -> int:
        div = soup.find("div", class_="paginazione_pagina_di")
        if not div:
            return 0
        m = re.search(r"(\d+) risultati", div.get_text())
        return int(m.group(1)) if m else 0

    @staticmethod
    def parse_listings(soup: BeautifulSoup) -> list[Annuncio]:
        results = []
        for panel in soup.find_all("div", class_="lib-panel"):
            try:
                titolo_tag = panel.find("div", class_="lib-header")
                titolo = titolo_tag.get_text(strip=True) if titolo_tag else ""

                desc_rows = panel.find_all("div", class_="lib-row lib-desc")
                indirizzo, comune = "", ""
                if desc_rows:
                    loc_p = desc_rows[0].find("p")
                    if loc_p:
                        spans = loc_p.get_text("|", strip=True).split("|")
                        indirizzo = spans[0] if len(spans) > 0 else ""
                        comune = spans[1] if len(spans) > 1 else ""

                descrizione = ""
                if len(desc_rows) > 1:
                    descrizione = desc_rows[1].get_text(strip=True)

                bg = panel.find("div", class_="lib-bg")
                categoria = ruolo = tipo_vendita = lotto = codice_asta = ""
                anno = None
                if bg:
                    bg_text = bg.get_text(" ", strip=True)
                    # Es: "IMMOBILI-IMMOBILE RESIDENZIALE | Ruolo: 316/2025 |
                    #      Vendita: Senza incanto |  | Lotto: LOTTO UNICO | Codice Asta: 4348204"
                    parts = [p.strip() for p in bg_text.split("|")]
                    for p in parts:
                        if p.startswith("Ruolo:"):
                            ruolo_full = p.replace("Ruolo:", "").strip()
                            if "/" in ruolo_full:
                                ruolo, anno = ruolo_full.split("/", 1)
                            else:
                                ruolo = ruolo_full
                        elif p.startswith("Vendita:"):
                            tipo_vendita = p.replace("Vendita:", "").strip()
                        elif p.startswith("Lotto:"):
                            lotto = p.replace("Lotto:", "").strip()
                        elif p.startswith("Codice Asta:"):
                            codice_asta = p.replace("Codice Asta:", "").strip()
                    if parts:
                        categoria = parts[0]

                prezzo_tag = panel.find("span", class_="price")
                prezzo_base = prezzo_tag.get_text(strip=True) if prezzo_tag else ""

                stato = "sconosciuto"
                if panel.find("span", class_="sfondo_green"):
                    stato = "gara da iniziare"
                elif panel.find("span", class_="sfondo_red"):
                    stato = "in corso o conclusa"

                link_tag = panel.find("a", class_="lib-button")
                link = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""

                results.append(Annuncio(
                    codice_asta=codice_asta,
                    titolo=titolo,
                    indirizzo=indirizzo,
                    comune=comune,
                    categoria=categoria,
                    ruolo=ruolo,
                    anno=anno,
                    tipo_vendita=tipo_vendita,
                    lotto=lotto,
                    prezzo_base=prezzo_base,
                    descrizione=descrizione,
                    link=link,
                    stato=stato,
                ))
            except Exception as e:
                log.warning(f"Errore parsing di un annuncio: {e}")
                continue
        return results

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def scrape_all(self, delay_seconds: float = 1.5) -> list[Annuncio]:
        soup = self.load_first_page()
        total_pages = self._total_pages(soup)
        total_results = self._total_results(soup)
        log.info(f"Totale annunci dichiarati dal sito: {total_results} su {total_pages} pagine")

        all_results = self.parse_listings(soup)
        log.info(f"Pagina 1: {len(all_results)} annunci estratti")

        for page in range(2, total_pages + 1):
            time.sleep(delay_seconds)  # cortesia verso il server
            soup = self.load_page(page)
            page_results = self.parse_listings(soup)
            log.info(f"Pagina {page}: {len(page_results)} annunci estratti")
            all_results.extend(page_results)

        log.info(f"Totale estratto: {len(all_results)} (atteso: {total_results})")
        if len(all_results) != total_results:
            log.warning(
                "Il numero di annunci estratti non coincide col totale dichiarato dal sito. "
                "Possibile che alcuni annunci siano duplicati tra pagine, o che la struttura "
                "HTML sia cambiata: controllare manualmente."
            )
        return all_results


def save_snapshot(annunci: list[Annuncio], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"snapshot_{timestamp}.json"
    data = {
        "data_estrazione": datetime.now().isoformat(),
        "totale": len(annunci),
        "annunci": [asdict(a) for a in annunci],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Snapshot salvato in {path}")
    return path


if __name__ == "__main__":
    scraper = TribunaleGenovaScraper()
    annunci = scraper.scrape_all()
    out_dir = Path(__file__).parent / "snapshots"
    save_snapshot(annunci, out_dir)
