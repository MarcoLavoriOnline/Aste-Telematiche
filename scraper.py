"""
Scraper per le aste immobiliari del Tribunale di Genova, versione
Playwright (browser headless reale).

Perche' questo cambio rispetto alla prima versione (requests + postback
manuale): abbiamo verificato con gli strumenti sviluppatore del browser
che la pagina, al caricamento, lancia in automatico una richiesta POST
verso se stessa per popolare i risultati - ma il contenuto di quella
POST non e' banale da replicare a mano (i campi visibili nel payload
risultavano vuoti, quindi la logica di innesco e' probabilmente gestita
in un modo poco prevedibile).

Con un browser headless vero (qui: Chromium via Playwright) tutto
questo diventa irrilevante: il browser esegue il JavaScript esattamente
come un utente reale, quindi vediamo la pagina "come la vede il
tribunale.genova.it" senza dover indovinare nulla.
"""

import re
import json
import time
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page

BASE_URL = "https://www.tribunale.genova.it/venditegiudiziarie/default.aspx?m=1"

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
    stato: str


def _total_pages_and_results(page: Page) -> tuple[int, int]:
    testo = page.locator(".paginazione_pagina_di").first.inner_text()
    m_pagine = re.search(r"Pagina \d+ di (\d+) pagine", testo)
    m_tot = re.search(r"(\d+) risultati", testo)
    pagine = int(m_pagine.group(1)) if m_pagine else 1
    totale = int(m_tot.group(1)) if m_tot else 0
    return pagine, totale


def _parse_current_page(page: Page) -> list[Annuncio]:
    """Estrae gli annunci dalla pagina attualmente renderizzata nel browser."""
    panels = page.locator(".lib-panel")
    count = panels.count()
    results = []

    for i in range(count):
        panel = panels.nth(i)
        try:
            titolo = panel.locator(".lib-header").first.inner_text().strip()

            desc_rows = panel.locator(".lib-row.lib-desc")
            indirizzo, comune, descrizione = "", "", ""
            if desc_rows.count() > 0:
                loc_text = desc_rows.nth(0).inner_text()
                parts = [p.strip() for p in loc_text.split("\n") if p.strip()]
                if len(parts) > 0:
                    indirizzo = parts[0]
                if len(parts) > 1:
                    comune = parts[1]
            if desc_rows.count() > 1:
                descrizione = desc_rows.nth(1).inner_text().strip()

            bg_text = ""
            bg_loc = panel.locator(".lib-bg")
            if bg_loc.count() > 0:
                bg_text = bg_loc.first.inner_text()
            bg_text = " ".join(bg_text.split())

            categoria = ruolo = tipo_vendita = lotto = codice_asta = ""
            anno = None
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

            prezzo_base = ""
            prezzo_loc = panel.locator(".price")
            if prezzo_loc.count() > 0:
                prezzo_base = prezzo_loc.first.inner_text().strip()

            stato = "sconosciuto"
            if panel.locator(".sfondo_green").count() > 0:
                stato = "gara da iniziare"
            elif panel.locator(".sfondo_red").count() > 0:
                stato = "in corso o conclusa"

            link = ""
            link_loc = panel.locator("a.lib-button")
            if link_loc.count() > 0:
                link = link_loc.first.get_attribute("href") or ""

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
            log.warning(f"Errore parsing annuncio #{i}: {e}")
            continue

    return results


def scrape_all(headless: bool = True, delay_seconds: float = 2.0) -> list[Annuncio]:
    all_results: list[Annuncio] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            locale="it-IT",
        )
        page = context.new_page()

        log.info("Apro la pagina di ricerca...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=60000)

        # Il sito NON carica i risultati da solo: serve cliccare esplicitamente
        # il bottone "AVVIA RICERCA" (anche lasciando tutti i filtri vuoti).
        log.info("Clicco il bottone 'AVVIA RICERCA'...")
        try:
            page.get_by_text("AVVIA RICERCA", exact=False).first.click(timeout=10000)
        except Exception as e:
            log.warning(f"Non sono riuscito a cliccare 'AVVIA RICERCA' col testo: {e}")
            log.warning("Provo un selettore alternativo...")
            # fallback: qualunque bottone/input con quel testo o vicino al form immobili
            page.locator("button:has-text('AVVIA RICERCA'), input[value*='AVVIA RICERCA']").first.click(timeout=10000)

        page.wait_for_load_state("networkidle", timeout=30000)

        try:
            page.wait_for_selector(".lib-panel", timeout=20000)
        except Exception:
            log.warning(
                "Nessun .lib-panel apparso entro 20s. Salvo screenshot e HTML per debug."
            )
            page.screenshot(path="debug_screenshot.png", full_page=True)
            Path("debug_page.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            return []

        pagine_totali, risultati_totali = _total_pages_and_results(page)
        log.info(f"Totale dichiarato: {risultati_totali} risultati su {pagine_totali} pagine")

        pagina_corrente = 1
        while True:
            log.info(f"Estraggo pagina {pagina_corrente}...")
            annunci_pagina = _parse_current_page(page)
            log.info(f"  -> {len(annunci_pagina)} annunci trovati in questa pagina")
            all_results.extend(annunci_pagina)

            if pagina_corrente >= pagine_totali:
                break

            next_num = pagina_corrente + 1
            selector_num = f"#ctl00_mainc_PrimaSel_lnk_btn_valore_{next_num}"
            selector_succ = "#ctl00_mainc_PrimaSel_lnk_btn_valore_succ"

            clicked = False
            if page.locator(selector_num).count() > 0:
                page.locator(selector_num).click()
                clicked = True
            elif page.locator(selector_succ).count() > 0:
                page.locator(selector_succ).click()
                clicked = True

            if not clicked:
                log.warning(
                    f"Non trovo il bottone per la pagina {next_num}: mi fermo qui "
                    f"(estratte {len(all_results)} su {risultati_totali} dichiarati)."
                )
                break

            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(delay_seconds)

            pagina_corrente += 1

        browser.close()

    log.info(f"Totale estratto: {len(all_results)} (dichiarato dal sito: {risultati_totali})")
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
    annunci = scrape_all()
    out_dir = Path(__file__).parent / "snapshots"
    save_snapshot(annunci, out_dir)
