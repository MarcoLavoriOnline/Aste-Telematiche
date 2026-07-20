# Scraper aste Tribunale di Genova

Estrae ogni giorno l'elenco completo degli annunci di vendita giudiziaria
dal sito ufficiale del Tribunale di Genova e segnala nuovi annunci,
annunci spariti (probabile aggiudicazione/ritiro) e cambi di stato.

## Come funziona

Il sito (`tribunale.genova.it/venditegiudiziarie/`) è un'applicazione
ASP.NET WebForms classica. La paginazione **non** è fatta con link
statici né con una API JSON: ogni "pagina successiva" è in realtà un
postback del form (`__doPostBack`) che porta con sé un token
`__VIEWSTATE` enorme, generato dal server ad ogni risposta.

Lo scraper simula esattamente questo comportamento:
1. Fa una GET alla pagina di ricerca → riceve il primo `__VIEWSTATE`
2. Fa una POST con `__EVENTTARGET` = il bottone "pagina 2" + il
   `__VIEWSTATE` ricevuto → riceve pagina 2 + nuovo `__VIEWSTATE`
3. Ripete finché non ha coperto tutte le pagine dichiarate dal sito
   (il numero totale è scritto in cima, es. "Pagina 1 di 7 pagine -
   133 risultati")

Non serve un browser headless (Playwright/Selenium): bastano
`requests` + `BeautifulSoup`, quindi è leggero e veloce anche su un
piccolo server.

## File

- `scraper.py` — logica di scraping e parsing dei singoli annunci
- `diff.py` — confronta l'ultimo snapshot col precedente
- `run_daily.py` — orchestratore da mettere in cron
- `snapshots/` — qui vengono salvati i JSON giornalieri (creata al
  primo avvio)

## Uso

```bash
pip install requests beautifulsoup4 lxml

# Un run singolo (scarica + salva snapshot + diff se disponibile)
python3 run_daily.py

# Solo scraping
python3 scraper.py

# Solo confronto tra gli ultimi due snapshot salvati
python3 diff.py
```

## Automazione con cron (Linux/Mac)

```bash
crontab -e
```

Aggiungi (esempio: ogni giorno alle 8:00):

```
0 8 * * * cd /percorso/aste-scraper && /usr/bin/python3 run_daily.py >> log.txt 2>&1
```

## ⚠️ IMPORTANTE — cosa NON ho potuto testare

Il mio ambiente di esecuzione non ha accesso di rete verso
`tribunale.genova.it` (solo verso repository di pacchetti). Ho quindi
potuto:

- ✅ Validare **la logica di parsing** (`parse_listings`) usando
  l'HTML reale che mi hai incollato — funziona correttamente su
  tutti i campi (titolo, indirizzo, comune, prezzo, ruolo, codice
  asta, stato, link)
- ✅ Validare **la logica di diff** con dati simulati
- ❌ **NON ho potuto testare la sequenza di postback reale**
  (`load_page` → click pagina 2, 3, ecc.) perché non riesco a
  raggiungere il sito da qui

**Quindi il primo run va fatto e osservato da te**, sul tuo computer.
Cose che potrebbero non funzionare al primo colpo e richiedere un
piccolo aggiustamento:

1. **Il nome del control di paginazione potrebbe essere leggermente
   diverso per pagine oltre la 4ª.** Nell'HTML che mi hai mandato
   vedo solo i bottoni "1, 2, 3, 4, >>" (perché eravamo a pagina 1).
   Il bottone ">>" ha `id="ctl00_mainc_PrimaSel_li_succ"` e usa lo
   stesso pattern `lnk_btn_valore_succ`. Se il sito usa uno schema a
   "finestra scorrevole" di pagine (mostra sempre 4-5 numeri intorno
   alla pagina corrente, non tutte e 7), potrebbe essere più
   affidabile **cliccare sempre ">>" invece che sul numero fisso**.
   Se noti che lo script si blocca o ripete la stessa pagina, dimmelo
   e sistemo la logica per usare `lnk_btn_valore_succ` invece dei
   numeri.
2. **`__EVENTVALIDATION`** — alcune installazioni ASP.NET richiedono
   anche questo campo nascosto per accettare il postback (protezione
   anti-tampering). Il codice lo gestisce già SE presente nell'HTML,
   ma se il sito lo richiede e non lo trova potresti ricevere una
   pagina di errore invece dei risultati.
3. **Rate limiting / blocco IP** — ho messo un `delay_seconds=1.5` tra
   una pagina e l'altra per cortesia verso il server. Se il sito
   blocca comunque le richieste automatiche, valuta di aumentare il
   delay o di aggiungere header più simili a un browser reale.

## Prossimi passi possibili

- Aggiungere l'invio di notifiche (email, Telegram) quando ci sono
  nuovi annunci, invece di dover controllare i log a mano
- Filtrare per categoria/comune di interesse prima del salvataggio
- Salvare anche il testo completo della "scheda dettagliata" (serve
  un secondo livello di scraping, sul link di ogni annuncio)
