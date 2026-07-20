"""
Script da eseguire ogni giorno (via cron): scrapa il sito, salva lo
snapshot, e se esiste uno snapshot precedente stampa/salva il diff.

Uso manuale:
    python3 run_daily.py

Uso in cron (es. ogni giorno alle 8:00):
    0 8 * * * cd /path/aste-scraper && /usr/bin/python3 run_daily.py >> log.txt 2>&1
"""

from pathlib import Path

from scraper import scrape_all, save_snapshot, log
from diff import latest_two_snapshots, compare, print_report

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def main():
    annunci = scrape_all()
    save_snapshot(annunci, SNAPSHOT_DIR)

    old, new = latest_two_snapshots(SNAPSHOT_DIR)
    if old and new:
        report = compare(old, new)
        print_report(report)
        # TODO: qui puoi collegare un invio email/telegram se vuoi
        # essere notificato invece di dover controllare i log a mano.
    else:
        log.info("Primo snapshot salvato: il confronto sara' disponibile dal prossimo run.")


if __name__ == "__main__":
    main()
