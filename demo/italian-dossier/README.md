# Alchimista - dossier dimostrativo italiano

> **ATTENZIONE: tutti i dati contenuti in questo dossier sono interamente sintetici. Persone, società, indirizzi, recapiti e identificatori non rappresentano soggetti reali e non devono essere usati per finalità operative.**

## Scenario

Aurora Sistemi S.r.l. sta realizzando il **Progetto Mercury**, un'iniziativa interna di integrazione e controllo dei dati. **Giulia Bianchi** è la responsabile del progetto; **Marco Rossi** è il consulente cybersecurity; **Francesca Romano** coordina la revisione dati per il fornitore esterno **Northstar Analytics S.r.l.**; **Laura Conti** segue amministrazione e operations.

I cinque documenti formano una storia coerente pensata per dimostrare:

- rilevamento PII italiano con Rizzo Lightweight (regex e checksum) e Rizzo Full (ML più regex);
- pseudonimizzazione in modalità STRICT;
- persistenza della libreria documentale;
- retrieval trasversale con citazioni apribili;
- conservazione nell'audit di detector, versione e revisione effettivamente applicati.

Gli identificatori fiscali e bancari sono generati deterministicamente da `generate_dossier.py` e validati localmente. Gli indirizzi email usano esclusivamente il dominio riservato `example.com` o suoi sottodomini.

## Documenti ed entità attese

### 1. `01_contratto_consulenza_marco_rossi.pdf`

- Persone: Marco Rossi, Giulia Bianchi.
- Organizzazione: Aurora Sistemi S.r.l.
- PII strutturata: indirizzo, email, telefono e codice fiscale checksum-validato di Marco Rossi.
- Altre entità: compenso di € 48.000,00, Progetto Mercury, date contrattuali.
- Fatto chiave: conservazione del contratto per **36 mesi** dalla chiusura del progetto.

### 2. `02_scheda_fornitore_northstar_analytics.pdf`

- Persone: Francesca Romano, Laura Conti.
- Organizzazioni: Northstar Analytics S.r.l., Aurora Sistemi S.r.l.
- PII e identificatori: Partita IVA checksum-validata, IBAN checksum-validato, PEC sintetica, email, telefoni e indirizzo.
- Fatto chiave: Northstar Analytics è qualificata per la revisione dei dati del Progetto Mercury.

### 3. `03_verbale_progetto_mercury.pdf`

- Persone: Giulia Bianchi, Marco Rossi, Francesca Romano, Laura Conti.
- Organizzazioni: Aurora Sistemi S.r.l., Northstar Analytics S.r.l.
- Fatti chiave: budget **€ 125.000,00**; project owner **Giulia Bianchi**; consegna **30 settembre 2026**; data review affidata a **Northstar Analytics S.r.l.**

### 4. `04_policy_conservazione_dati.pdf`

- PII volutamente ridotta; prevalgono ruoli e categorie documentali.
- Fatti chiave: documenti contrattuali **36 mesi**; documenti tecnici **18 mesi**; log operativi **90 giorni**.
- Concetti di governance: legal hold, cancellazione verificata, minimizzazione e ricevuta tecnica.

### 5. `05_segnalazione_incidente.pdf`

- Persone: Laura Conti, Giulia Bianchi, Marco Rossi, Francesca Romano.
- Organizzazioni: Aurora Sistemi S.r.l., Northstar Analytics S.r.l.
- PII: molteplici email e telefoni inseriti in una narrazione naturale.
- Timeline: apertura alle **08:42 del 18 giugno 2026**, contenimento concluso alle **10:18**.
- Fatto chiave: non sono emerse evidenze di esfiltrazione; Northstar effettua un controllo incrociato sui dati Mercury.

## Fatti di retrieval attesi

1. Il budget del Progetto Mercury è € 125.000,00.
2. Giulia Bianchi è la project owner.
3. La consegna prevista è il 30 settembre 2026.
4. Northstar Analytics S.r.l. svolge la revisione dei dati.
5. Il compenso contrattuale di Marco Rossi è € 48.000,00.
6. I periodi di conservazione sono 36 mesi, 18 mesi e 90 giorni secondo la categoria.
7. L'incidente del 18 giugno 2026 è stato contenuto alle 10:18 senza evidenze di esfiltrazione.

## Cinque domande suggerite per la demo

1. **Qual è il budget del Progetto Mercury, chi ne è responsabile e quando è prevista la consegna?**
2. **Quale società svolge la revisione dei dati e chi è la sua referente operativa?**
3. **Qual è il compenso di Marco Rossi e per quanto tempo deve essere conservato il suo contratto?**
4. **Confronta i tempi di conservazione di documenti contrattuali, documenti tecnici e log operativi.**
5. **Ricostruisci la cronologia dell'incidente del 18 giugno 2026 e indica le persone coinvolte, citando le fonti.**

## Rigenerazione

Dal root del repository, usando un ambiente che includa ReportLab:

```powershell
python demo/italian-dossier/generate_dossier.py
```

Lo script non modifica il codice o la configurazione di Alchimista; sovrascrive soltanto i cinque PDF della presente directory.
