"""
Script diagnostico: fa una singola richiesta GET al sito del Tribunale
di Genova e salva TUTTO quello che riceve (headers + html completo),
cosi' possiamo capire perche' da GitHub Actions il sito risponde con
0 risultati invece dei risultati reali.

Non fa parsing intelligente: e' solo per ispezionare a occhio nudo
cosa arriva davvero.
"""
import requests

BASE_URL = "https://www.tribunale.genova.it/venditegiudiziarie/default.aspx?m=1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)

resp = session.get(BASE_URL, timeout=30)

print(f"Status code: {resp.status_code}")
print(f"URL finale (dopo eventuali redirect): {resp.url}")
print(f"Cookie ricevuti: {dict(session.cookies)}")
print(f"Lunghezza risposta: {len(resp.text)} caratteri")
print()
print("--- Primi 500 caratteri della risposta ---")
print(resp.text[:500])
print()
print("--- Contiene 'risultati'? ---")
print("risultati" in resp.text)
print()
print("--- Contiene 'lib-panel' (i box annuncio)? ---")
print("lib-panel" in resp.text)

# Salva tutto su file per ispezione completa
with open("debug_response.html", "w", encoding="utf-8") as f:
    f.write(resp.text)

with open("debug_headers.txt", "w", encoding="utf-8") as f:
    f.write("RESPONSE HEADERS:\n")
    for k, v in resp.headers.items():
        f.write(f"{k}: {v}\n")
    f.write("\nREQUEST HEADERS INVIATI:\n")
    for k, v in resp.request.headers.items():
        f.write(f"{k}: {v}\n")

print()
print("Salvati: debug_response.html e debug_headers.txt")
