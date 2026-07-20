"""
Genera una pagina HTML statica (docs/index.html) a partire dall'ultimo
snapshot salvato, evidenziando gli annunci nuovi rispetto al giorno
precedente (se disponibile un diff).

La pagina viene pubblicata gratuitamente da GitHub Pages, puntando
alla cartella docs/ del branch main.
"""
import json
from pathlib import Path
from datetime import datetime

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
OUTPUT_DIR = Path(__file__).parent / "docs"
GEOCODE_CACHE_PATH = Path(__file__).parent / "geocode_cache.json"


def _load_geocode_cache() -> dict:
    if GEOCODE_CACHE_PATH.exists():
        return json.loads(GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _latest_snapshot() -> dict:
    files = sorted(SNAPSHOT_DIR.glob("snapshot_*.json"))
    if not files:
        raise FileNotFoundError("Nessuno snapshot trovato in snapshots/")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _latest_diff() -> dict | None:
    files = sorted(SNAPSHOT_DIR.glob("diff_*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _prezzo_a_numero(prezzo_str: str) -> float:
    """'€ 12.345,67' -> 12345.67 (per poter ordinare per prezzo)."""
    pulito = (
        prezzo_str.replace("€", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(pulito)
    except ValueError:
        return 0.0


def genera_html():
    snapshot = _latest_snapshot()
    diff = _latest_diff()
    geocode_cache = _load_geocode_cache()

    codici_nuovi = set()
    if diff:
        codici_nuovi = {a["codice_asta"] for a in diff.get("nuovi", [])}

    annunci = snapshot["annunci"]
    # Ordina: prima i nuovi, poi per prezzo crescente
    annunci_ordinati = sorted(
        annunci,
        key=lambda a: (a["codice_asta"] not in codici_nuovi, _prezzo_a_numero(a["prezzo_base"])),
    )

    # Prepara i dati per i marker della mappa (solo gli annunci geocodificati con successo)
    markers = []
    for a in annunci:
        coords = geocode_cache.get(a["codice_asta"])
        if coords and coords.get("lat") and coords.get("lon"):
            markers.append({
                "lat": coords["lat"],
                "lon": coords["lon"],
                "titolo": a["titolo"],
                "comune": a["comune"],
                "prezzo": a["prezzo_base"],
                "link": a["link"],
                "nuovo": a["codice_asta"] in codici_nuovi,
            })
    markers_json = json.dumps(markers, ensure_ascii=False)
    n_geocodificati = len(markers)
    n_totale = len(annunci)

    data_estrazione = datetime.fromisoformat(snapshot["data_estrazione"])
    data_fmt = data_estrazione.strftime("%d/%m/%Y alle %H:%M")

    cards_html = []
    for a in annunci_ordinati:
        is_nuovo = a["codice_asta"] in codici_nuovi
        badge_nuovo = '<span class="badge-nuovo">NUOVO</span>' if is_nuovo else ""
        badge_stato = (
            '<span class="badge-stato badge-verde">Gara da iniziare</span>'
            if a["stato"] == "gara da iniziare"
            else '<span class="badge-stato badge-rossa">In corso / conclusa</span>'
            if a["stato"] == "in corso o conclusa"
            else ""
        )
        cards_html.append(f"""
        <div class="card{' card-nuovo' if is_nuovo else ''}">
            <div class="card-header">
                {badge_nuovo}
                <h3>{a['titolo']}</h3>
                {badge_stato}
            </div>
            <div class="card-price">{a['prezzo_base']}</div>
            <div class="card-location">📍 {a['indirizzo']} — {a['comune']}</div>
            <div class="card-meta">
                {a['categoria']} · Ruolo {a['ruolo']}/{a['anno'] or ''} · Lotto {a['lotto']} · Codice {a['codice_asta']}
            </div>
            <div class="card-desc">{a['descrizione']}</div>
            <a href="{a['link']}" target="_blank" class="card-link">Scheda dettagliata su Aste Giudiziarie →</a>
        </div>
        """)

    n_nuovi = len(codici_nuovi)
    banner_nuovi = ""
    if n_nuovi > 0:
        banner_nuovi = f"""
        <div class="banner-nuovi">
            🆕 {n_nuovi} nuovo/i annuncio/i da ieri!
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aste Tribunale di Genova</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #f4f5f7;
        margin: 0;
        padding: 0;
        color: #1a1a1a;
    }}
    header {{
        background: #0b3d66;
        color: white;
        padding: 24px 20px;
        text-align: center;
    }}
    header h1 {{ margin: 0 0 6px 0; font-size: 1.5rem; }}
    header p {{ margin: 0; opacity: 0.85; font-size: 0.9rem; }}
    .container {{
        max-width: 900px;
        margin: 0 auto;
        padding: 20px;
    }}
    .banner-nuovi {{
        background: #e6f4ea;
        border: 1px solid #34a853;
        color: #1e7e34;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-weight: 600;
        text-align: center;
    }}
    .stats {{
        display: flex;
        gap: 12px;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .stat-box {{
        background: white;
        border-radius: 8px;
        padding: 12px 16px;
        flex: 1;
        min-width: 140px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .stat-box .num {{ font-size: 1.4rem; font-weight: 700; color: #0b3d66; }}
    .stat-box .label {{ font-size: 0.8rem; color: #666; }}
    #map {{
        height: 350px;
        border-radius: 10px;
        margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .map-note {{
        font-size: 0.78rem;
        color: #888;
        margin: -14px 0 20px 4px;
    }}
    .card {{
        background: white;
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .card-nuovo {{
        border-left: 4px solid #34a853;
    }}
    .card-header {{
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }}
    .card-header h3 {{
        margin: 0;
        font-size: 1.05rem;
        flex: 1;
    }}
    .badge-nuovo {{
        background: #34a853;
        color: white;
        font-size: 0.7rem;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 10px;
    }}
    .badge-stato {{
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 10px;
        font-weight: 600;
    }}
    .badge-verde {{ background: #e6f4ea; color: #1e7e34; }}
    .badge-rossa {{ background: #fce8e6; color: #c5221f; }}
    .card-price {{
        font-size: 1.3rem;
        font-weight: 700;
        color: #0b3d66;
        margin: 6px 0;
    }}
    .card-location {{ font-size: 0.9rem; color: #444; margin-bottom: 4px; }}
    .card-meta {{ font-size: 0.78rem; color: #888; margin-bottom: 8px; }}
    .card-desc {{
        font-size: 0.88rem;
        color: #333;
        line-height: 1.4;
        margin-bottom: 10px;
    }}
    .card-link {{
        display: inline-block;
        font-size: 0.85rem;
        color: #0b3d66;
        font-weight: 600;
        text-decoration: none;
    }}
    .card-link:hover {{ text-decoration: underline; }}
    footer {{
        text-align: center;
        padding: 24px;
        color: #888;
        font-size: 0.8rem;
    }}
</style>
</head>
<body>
<header>
    <h1>🏛️ Aste Immobiliari — Tribunale di Genova</h1>
    <p>Aggiornato il {data_fmt}</p>
</header>
<div class="container">
    {banner_nuovi}
    <div class="stats">
        <div class="stat-box">
            <div class="num">{len(annunci)}</div>
            <div class="label">Annunci totali</div>
        </div>
        <div class="stat-box">
            <div class="num">{n_nuovi}</div>
            <div class="label">Nuovi da ieri</div>
        </div>
    </div>

    <div id="map"></div>
    <p class="map-note">📍 {n_geocodificati} di {n_totale} annunci mostrati sulla mappa (gli altri non hanno un indirizzo geocodificabile).</p>

    {''.join(cards_html)}
</div>
<footer>
    Dati raccolti automaticamente ogni giorno dal
    <a href="https://www.tribunale.genova.it/venditegiudiziarie/default.aspx?m=1" target="_blank">sito ufficiale del Tribunale di Genova</a>.
    Uso personale, fonte sempre citata su ogni annuncio.
</footer>
<script>
    const markers = {markers_json};
    const map = L.map('map').setView([44.4, 9.0], 9);  // centro approssimativo su Genova/Liguria

    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }}).addTo(map);

    const bounds = [];
    markers.forEach(m => {{
        const icon = m.nuovo
            ? L.divIcon({{className: '', html: '<div style="background:#34a853;width:14px;height:14px;border-radius:50%;border:2px solid white;box-shadow:0 0 3px rgba(0,0,0,0.4);"></div>', iconSize: [14,14]}})
            : L.divIcon({{className: '', html: '<div style="background:#0b3d66;width:12px;height:12px;border-radius:50%;border:2px solid white;box-shadow:0 0 3px rgba(0,0,0,0.4);"></div>', iconSize: [12,12]}});

        const marker = L.marker([m.lat, m.lon], {{icon: icon}}).addTo(map);
        marker.bindPopup(
            `<strong>${{m.titolo}}</strong><br>${{m.comune}}<br>${{m.prezzo}}<br><a href="${{m.link}}" target="_blank">Scheda dettagliata →</a>`
        );
        bounds.push([m.lat, m.lon]);
    }});

    if (bounds.length > 0) {{
        map.fitBounds(bounds, {{padding: [30, 30]}});
    }}
</script>
</body>
</html>
"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"Pagina generata: {OUTPUT_DIR / 'index.html'} ({len(annunci)} annunci, {n_nuovi} nuovi)")


if __name__ == "__main__":
    genera_html()
