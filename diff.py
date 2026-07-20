"""
Confronta l'ultimo snapshot con quello precedente e segnala:
- annunci NUOVI (codice_asta comparso solo nell'ultimo)
- annunci SPARITI (probabilmente aggiudicati, ritirati, o rinviati)
- variazioni di STATO (es. da "gara da iniziare" a "in corso o conclusa")
"""

import json
from pathlib import Path
from typing import Optional


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_two_snapshots(snapshot_dir: Path) -> tuple[Optional[Path], Optional[Path]]:
    """Ritorna (penultimo, ultimo) snapshot per data nel nome file."""
    files = sorted(snapshot_dir.glob("snapshot_*.json"))
    if len(files) < 2:
        return (None, files[-1] if files else None)
    return files[-2], files[-1]


def compare(old_path: Path, new_path: Path) -> dict:
    old_data = _load(old_path)
    new_data = _load(new_path)

    old_by_code = {a["codice_asta"]: a for a in old_data["annunci"] if a["codice_asta"]}
    new_by_code = {a["codice_asta"]: a for a in new_data["annunci"] if a["codice_asta"]}

    old_codes = set(old_by_code)
    new_codes = set(new_by_code)

    nuovi = [new_by_code[c] for c in (new_codes - old_codes)]
    spariti = [old_by_code[c] for c in (old_codes - new_codes)]

    cambi_stato = []
    for c in old_codes & new_codes:
        if old_by_code[c]["stato"] != new_by_code[c]["stato"]:
            cambi_stato.append({
                "codice_asta": c,
                "titolo": new_by_code[c]["titolo"],
                "comune": new_by_code[c]["comune"],
                "stato_precedente": old_by_code[c]["stato"],
                "stato_attuale": new_by_code[c]["stato"],
            })

    return {
        "data_confronto_da": old_data["data_estrazione"],
        "data_confronto_a": new_data["data_estrazione"],
        "totale_precedente": len(old_by_code),
        "totale_attuale": len(new_by_code),
        "nuovi": nuovi,
        "spariti": spariti,
        "cambi_stato": cambi_stato,
    }


def print_report(report: dict):
    print(f"Confronto: {report['data_confronto_da']} -> {report['data_confronto_a']}")
    print(f"Totale annunci: {report['totale_precedente']} -> {report['totale_attuale']}")
    print()

    if report["nuovi"]:
        print(f"🆕 NUOVI ANNUNCI ({len(report['nuovi'])}):")
        for a in report["nuovi"]:
            print(f"  - [{a['codice_asta']}] {a['titolo']} - {a['comune']} - {a['prezzo_base']}")
            print(f"    {a['link']}")
    else:
        print("Nessun nuovo annuncio.")
    print()

    if report["spariti"]:
        print(f"❌ ANNUNCI SPARITI ({len(report['spariti'])}) - probabile aggiudicazione/ritiro:")
        for a in report["spariti"]:
            print(f"  - [{a['codice_asta']}] {a['titolo']} - {a['comune']} - {a['prezzo_base']}")
    else:
        print("Nessun annuncio sparito.")
    print()

    if report["cambi_stato"]:
        print(f"🔄 CAMBI DI STATO ({len(report['cambi_stato'])}):")
        for c in report["cambi_stato"]:
            print(f"  - [{c['codice_asta']}] {c['titolo']} - {c['comune']}: "
                  f"{c['stato_precedente']} -> {c['stato_attuale']}")


if __name__ == "__main__":
    import sys
    snapshot_dir = Path(__file__).parent / "snapshots"
    old, new = latest_two_snapshots(snapshot_dir)
    if not old or not new:
        print("Servono almeno 2 snapshot per fare un confronto. "
              "Fai girare scraper.py per un paio di giorni di fila.")
        sys.exit(0)
    report = compare(old, new)
    print_report(report)

    report_path = snapshot_dir / f"diff_{Path(new).stem.replace('snapshot_', '')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport salvato in {report_path}")
