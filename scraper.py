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
from bs4 import BeautifulSoup

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


def _current_page(page: Page) -> int:
    testo = page.locator(".paginazione_pagina_di").first.inner_text()
    m = re.search(r"Pagina (\d+) di", testo)
    return int(m.group(1)) if m else 1


def _total_pages_and_results(page: Page) -> tuple[int, int]:
    testo = page.locator(".paginazione_pagina_di").first.inner_text()
    m_pagine = re.search(r"Pagina \d+ di (\d+) pagine", testo)
    m_tot = re.search(r"(\d+) risultati", testo)
    pagine = int(m_pagine.group(1)) if m_pagine else 1
    totale = int(m_tot.group(1)) if m_tot else 0
    return pagine, totale


def _parse_current_page(page: Page) -> list[Annuncio]:
    """
    Estrae gli annunci dalla pagina attualmente renderizzata nel browser.

    Nota tecnica: invece di usare i locator/inner_text di Playwright per
    separare indirizzo e comune (che sono su elementi <em> inline, quindi
    Playwright li restituisce come UNA riga sola, senza un vero "a capo"
    utilizzabile per separarli), prendiamo l'HTML grezzo di ogni pannello
    e lo interpretiamo con BeautifulSoup, che invece riesce a distinguere
    i due pezzi di testo separati dai tag <em> (get_text con separatore).
    Questo e' lo stesso approccio, gia' validato, usato nella primissima
    versione dello scraper (basata su requests).
    """
    panels_html = page.locator(".lib-panel").evaluate_all(
        "elements => elements.map(el => el.outerHTML)"
    )
    results = []

    for panel_html in panels_html:
        try:
            panel = BeautifulSoup(panel_html, "lxml")

            titolo_tag = panel.find(class_="lib-header")
            titolo = titolo_tag.get_text(strip=True) if titolo_tag else ""

            desc_rows = panel.find_all(class_="lib-desc")
            indirizzo, comune, descrizione = "", "", ""
            if desc_rows:
                loc_p = desc_rows[0].find("p")
                if loc_p:
                    spans = loc_p.get_text("|", strip=True).split("|")
                    indirizzo = spans[0].strip() if len(spans) > 0 else ""
                    comune = spans[1].strip() if len(spans) > 1 else ""
            if len(desc_rows) > 1:
                descrizione = desc_rows[1].get_text(strip=True)

            bg = panel.find(class_="lib-bg")
            categoria = ruolo = tipo_vendita = lotto = codice_asta = ""
            anno = None
            if bg:
                bg_text = " ".join(bg.get_text(" ", strip=True).split())
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

            prezzo_tag = panel.find(class_="price")
            prezzo_base = prezzo_tag.get_text(strip=True) if prezzo_tag else ""

            stato = "sconosciuto"
            if panel.find(class_="sfondo_green"):
                stato = "gara da iniziare"
            elif panel.find(class_="sfondo_red"):
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

            # La paginazione del sito usa una "finestra scorrevole": non tutti
            # i numeri di pagina sono sempre presenti come pulsanti. Quindi,
            # invece di assumere che esista il pulsante "pagina N+1", leggiamo
            # dinamicamente quali pulsanti-numero sono disponibili ORA e
            # clicchiamo il più piccolo tra quelli superiori alla pagina
            # corrente. Se non c'e' nessun numero utile, usiamo il pulsante
            # ">>" (id ...li_succ).
            bottoni = page.locator("[id^='ctl00_mainc_PrimaSel_lnk_btn_valore_']")
            n_bottoni = bottoni.count()

            candidati = []  # lista di (numero_pagina, locator)
            succ_locator = None
            for i in range(n_bottoni):
                b = bottoni.nth(i)
                b_id = b.get_attribute("id") or ""
                if b_id.endswith("_succ"):
                    succ_locator = b
                    continue
                if b_id.endswith("_prec"):
                    continue
                testo_bottone = (b.inner_text() or "").strip()
                if testo_bottone.isdigit():
                    candidati.append((int(testo_bottone), b))

            candidati_validi = [c for c in candidati if c[0] > pagina_corrente]
            candidati_validi.sort(key=lambda c: c[0])

            clicked = False
            if candidati_validi:
                candidati_validi[0][1].click()
                clicked = True
            elif succ_locator is not None:
                succ_locator.click()
                clicked = True

            if not clicked:
                log.warning(
                    f"Nessun pulsante di paginazione utile trovato dopo la pagina "
                    f"{pagina_corrente}: mi fermo qui "
                    f"(estratte {len(all_results)} su {risultati_totali} dichiarati)."
                )
                break

            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(delay_seconds)

            # Non assumiamo che sia "pagina_corrente + 1": rileggiamo dal sito
            # quale pagina abbiamo effettivamente raggiunto.
            nuova_pagina = _current_page(page)
            if nuova_pagina <= pagina_corrente:
                log.warning(
                    f"Dopo il click la pagina dichiarata dal sito ({nuova_pagina}) "
                    f"non e' avanzata rispetto a prima ({pagina_corrente}): mi fermo "
                    f"per evitare un ciclo infinito."
                )
                break
            pagina_corrente = nuova_pagina

        browser.close()

    log.info(f"Totale estratto: {len(all_results)} (dichiarato dal sito: {risultati_totali})")

    # Rete di sicurezza: se per qualche motivo una pagina fosse stata letta
    # due volte, deduplichiamo per codice_asta (che dovrebbe essere univoco).
    visti = set()
    risultati_unici = []
    for a in all_results:
        chiave = a.codice_asta or a.link  # fallback se codice_asta manca
        if chiave in visti:
            continue
        visti.add(chiave)
        risultati_unici.append(a)

    if len(risultati_unici) != len(all_results):
        log.info(
            f"Rimossi {len(all_results) - len(risultati_unici)} duplicati "
            f"(probabile doppia lettura di una pagina)."
        )

    return risultati_unici
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
