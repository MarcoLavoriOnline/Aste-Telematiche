"""
Se l'ultimo confronto (diff) ha rilevato annunci nuovi, apre una
GitHub Issue nel repository. GitHub manda automaticamente una email
di notifica al proprietario del repository quando viene aperta una
issue - quindi questo ci dà le notifiche "gratis", senza dover
configurare bot Telegram o server email.

Usa il token GITHUB_TOKEN che GitHub Actions fornisce automaticamente
ad ogni esecuzione (nessun segreto da configurare a mano).
"""
import json
import os
from pathlib import Path

import requests

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _latest_diff() -> dict | None:
    files = sorted(SNAPSHOT_DIR.glob("diff_*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _formatta_corpo_issue(diff: dict) -> str:
    righe = [
        f"Confronto dal {diff['data_confronto_da']} al {diff['data_confronto_a']}",
        "",
    ]

    nuovi = diff.get("nuovi", [])
    if nuovi:
        righe.append(f"## 🆕 {len(nuovi)} nuovo/i annuncio/i\n")
        for a in nuovi:
            righe.append(
                f"- **{a['titolo']}** — {a['comune']} — {a['prezzo_base']}\n"
                f"  [Scheda dettagliata]({a['link']})"
            )
        righe.append("")

    spariti = diff.get("spariti", [])
    if spariti:
        righe.append(f"## ❌ {len(spariti)} annuncio/i sparito/i (probabile aggiudicazione/ritiro)\n")
        for a in spariti:
            righe.append(f"- {a['titolo']} — {a['comune']} — {a['prezzo_base']}")
        righe.append("")

    cambi = diff.get("cambi_stato", [])
    if cambi:
        righe.append(f"## 🔄 {len(cambi)} cambio/i di stato\n")
        for c in cambi:
            righe.append(
                f"- {c['titolo']} — {c['comune']}: "
                f"{c['stato_precedente']} → {c['stato_attuale']}"
            )
        righe.append("")

    righe.append("---")
    righe.append("_Vai alla pagina completa con tutti gli annunci per i dettagli._")

    return "\n".join(righe)


def crea_issue_se_ci_sono_novita():
    diff = _latest_diff()
    if not diff:
        print("Nessun diff disponibile ancora (primo run): nessuna notifica da inviare.")
        return

    n_nuovi = len(diff.get("nuovi", []))
    n_spariti = len(diff.get("spariti", []))
    n_cambi = len(diff.get("cambi_stato", []))

    if n_nuovi == 0 and n_spariti == 0 and n_cambi == 0:
        print("Nessuna novita' rispetto a ieri: nessuna notifica da inviare.")
        return

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")  # es. "utente/nome-repo"
    if not token or not repo:
        print("GITHUB_TOKEN o GITHUB_REPOSITORY non disponibili: siamo fuori da GitHub Actions?")
        return

    titolo = f"Aggiornamento aste: {n_nuovi} nuovi, {n_spariti} spariti, {n_cambi} cambi stato"
    corpo = _formatta_corpo_issue(diff)

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.post(url, headers=headers, json={"title": titolo, "body": corpo})

    if resp.status_code == 201:
        print(f"Issue creata: {resp.json().get('html_url')}")
    else:
        print(f"Errore nella creazione della issue: {resp.status_code} - {resp.text}")


if __name__ == "__main__":
    crea_issue_se_ci_sono_novita()
