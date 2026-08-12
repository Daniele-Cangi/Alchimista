"""Generate the fully synthetic Italian demonstration dossier for Alchimista."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_DIR = Path(__file__).resolve().parent
SYNTHETIC_FOOTER = "DOCUMENTO DIMOSTRATIVO — DATI INTERAMENTE SINTETICI"

NAVY = colors.HexColor("#16263A")
INK = colors.HexColor("#233247")
MUTED = colors.HexColor("#66758A")
TEAL = colors.HexColor("#0F8A83")
PALE_TEAL = colors.HexColor("#EAF6F4")
BLUE = colors.HexColor("#2563A6")
PALE_BLUE = colors.HexColor("#EDF4FB")
LINE = colors.HexColor("#D8E0E9")
PAPER = colors.HexColor("#F7F9FC")
AMBER = colors.HexColor("#B7791F")
PALE_AMBER = colors.HexColor("#FFF8E8")


def _register_fonts() -> tuple[str, str]:
    candidates = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("DossierSans", str(regular)))
            pdfmetrics.registerFont(TTFont("DossierSansBold", str(bold)))
            return "DossierSans", "DossierSansBold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = _register_fonts()

BODY = ParagraphStyle(
    "Body",
    fontName=FONT,
    fontSize=9.4,
    leading=14.2,
    textColor=INK,
    spaceAfter=7,
)
SMALL = ParagraphStyle(
    "Small",
    parent=BODY,
    fontSize=8,
    leading=11.5,
    textColor=MUTED,
    spaceAfter=4,
)
TABLE_TEXT = ParagraphStyle(
    "TableText",
    parent=BODY,
    fontSize=8.2,
    leading=11.2,
    spaceAfter=0,
)
TABLE_HEAD = ParagraphStyle(
    "TableHead",
    parent=TABLE_TEXT,
    fontName=FONT_BOLD,
    textColor=colors.white,
)
H1 = ParagraphStyle(
    "H1",
    fontName=FONT_BOLD,
    fontSize=23,
    leading=27,
    textColor=NAVY,
    spaceAfter=7,
)
H2 = ParagraphStyle(
    "H2",
    fontName=FONT_BOLD,
    fontSize=13.5,
    leading=17,
    textColor=NAVY,
    spaceBefore=12,
    spaceAfter=6,
)
H3 = ParagraphStyle(
    "H3",
    fontName=FONT_BOLD,
    fontSize=10.4,
    leading=13,
    textColor=BLUE,
    spaceBefore=7,
    spaceAfter=4,
)
KICKER = ParagraphStyle(
    "Kicker",
    fontName=FONT_BOLD,
    fontSize=7.4,
    leading=9,
    textColor=TEAL,
    tracking=1.4,
    spaceAfter=5,
)
CALLOUT = ParagraphStyle(
    "Callout",
    parent=BODY,
    fontSize=9,
    leading=13.2,
    spaceAfter=0,
)
SIGNATURE = ParagraphStyle(
    "Signature",
    parent=SMALL,
    alignment=TA_CENTER,
    textColor=INK,
)


CF_ODD = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17,
    "8": 19, "9": 21, "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13,
    "G": 15, "H": 17, "I": 19, "J": 21, "K": 2, "L": 4, "M": 18, "N": 20,
    "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14, "U": 16, "V": 10,
    "W": 22, "X": 25, "Y": 24, "Z": 23,
}


def codice_fiscale(partial: str) -> str:
    partial = partial.upper()
    if len(partial) != 15 or not partial.isalnum():
        raise ValueError("The codice fiscale partial value must contain 15 alphanumeric characters")
    total = sum(
        CF_ODD[value] if index % 2 == 0 else (int(value) if value.isdigit() else ord(value) - 65)
        for index, value in enumerate(partial)
    )
    return partial + chr(65 + total % 26)


def partita_iva(base: str) -> str:
    if len(base) != 10 or not base.isdigit():
        raise ValueError("The Partita IVA base value must contain 10 digits")
    total = 0
    for index, value in enumerate(map(int, base)):
        if index % 2 == 0:
            total += value
        else:
            doubled = value * 2
            total += doubled - 9 if doubled > 9 else doubled
    return base + str((10 - total % 10) % 10)


def italian_iban(cin: str, abi: str, cab: str, account: str) -> str:
    bban = f"{cin.upper()}{abi}{cab}{account}"
    if len(bban) != 23 or not bban.isalnum():
        raise ValueError("The Italian BBAN must contain 23 alphanumeric characters")
    rearranged = bban + "IT00"
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
    check_digits = 98 - int(numeric) % 97
    return f"IT{check_digits:02d}{bban}"


MARCO_CF = codice_fiscale("RSSMRC85T10H501")
NORTHSTAR_PIVA = partita_iva("9147283056")
NORTHSTAR_IBAN = italian_iban("N", "99999", "99999", "000000483726")
NORTHSTAR_IBAN_PRINT = " ".join(NORTHSTAR_IBAN[index:index + 4] for index in range(0, len(NORTHSTAR_IBAN), 4))


def _iban_valid(value: str) -> bool:
    compact = "".join(value.split()).upper()
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
    return int(numeric) % 97 == 1


assert MARCO_CF == "RSSMRC85T10H501Q"
assert NORTHSTAR_PIVA == "91472830560"
assert _iban_valid(NORTHSTAR_IBAN)


def para(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def section(title: str) -> Paragraph:
    return para(title, H2)


def subsection(title: str) -> Paragraph:
    return para(title, H3)


def bullets(items: Iterable[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(para(item, BODY), leftIndent=0) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=16,
        bulletFontName=FONT,
        bulletFontSize=6,
        bulletColor=TEAL,
        spaceAfter=5,
    )


def table(
    rows: list[list[str | Paragraph]],
    widths: list[float],
    *,
    header: bool = True,
    compact: bool = False,
) -> Table:
    converted: list[list[Paragraph]] = []
    for row_index, row in enumerate(rows):
        converted.append(
            [
                value if isinstance(value, Paragraph) else para(str(value), TABLE_HEAD if header and row_index == 0 else TABLE_TEXT)
                for value in row
            ]
        )
    result = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8 if not compact else 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8 if not compact else 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7 if not compact else 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7 if not compact else 5),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PAPER]),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        )
    result.setStyle(TableStyle(style))
    result.spaceAfter = 9
    return result


def key_value_table(rows: list[tuple[str, str]], label_width: float = 45 * mm) -> Table:
    converted = [[para(label, ParagraphStyle("KVLabel", parent=TABLE_TEXT, fontName=FONT_BOLD, textColor=NAVY)), para(value, TABLE_TEXT)] for label, value in rows]
    result = Table(converted, colWidths=[label_width, 174 * mm - label_width], hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    result.spaceAfter = 9
    return result


def callout(text: str, *, tone: str = "teal") -> Table:
    background, accent = (PALE_AMBER, AMBER) if tone == "amber" else (PALE_TEAL, TEAL)
    result = Table([[para(text, CALLOUT)]], colWidths=[174 * mm], hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.6, accent),
                ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    result.spaceAfter = 10
    return result


def title_block(kind: str, title: str, metadata: list[tuple[str, str]]) -> list:
    return [
        para(kind.upper(), KICKER),
        para(title, H1),
        Spacer(1, 2 * mm),
        key_value_table(metadata, label_width=36 * mm),
        Spacer(1, 2 * mm),
    ]


def signatures(left: str, right: str) -> Table:
    result = Table(
        [[para("Firma", SIGNATURE), para("Firma", SIGNATURE)], [Spacer(1, 18 * mm), Spacer(1, 18 * mm)], [para(left, SIGNATURE), para(right, SIGNATURE)]],
        colWidths=[84 * mm, 84 * mm],
        hAlign="CENTER",
    )
    result.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 2), (-1, 2), 0.6, MUTED),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return result


class DossierDocument(BaseDocTemplate):
    def __init__(self, path: Path, *, document_id: str, document_title: str):
        super().__init__(
            str(path),
            pagesize=A4,
            title=document_title,
            author="Aurora Sistemi S.r.l. - scenario sintetico Alchimista",
            subject="Dossier dimostrativo interamente sintetico",
            creator="Alchimista demo dossier generator",
        )
        self.document_id = document_id
        frame = Frame(18 * mm, 23 * mm, 174 * mm, 240 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="dossier", frames=[frame], onPage=self._draw_page)])

    def _draw_page(self, canvas, doc) -> None:
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 25 * mm, width, 25 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(FONT_BOLD, 13)
        canvas.drawString(18 * mm, height - 12 * mm, "AURORA SISTEMI")
        canvas.setFont(FONT, 6.7)
        canvas.setFillColor(colors.HexColor("#BFD5E8"))
        canvas.drawString(18 * mm, height - 17.2 * mm, "GOVERNANCE  /  PRIVACY  /  EVIDENZE")
        canvas.setFont(FONT_BOLD, 7.1)
        canvas.setFillColor(colors.HexColor("#86E0D8"))
        canvas.drawRightString(width - 18 * mm, height - 12 * mm, "DATI SINTETICI")
        canvas.setFont(FONT, 6.8)
        canvas.setFillColor(colors.white)
        canvas.drawRightString(width - 18 * mm, height - 17.2 * mm, self.document_id)

        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 18 * mm, width - 18 * mm, 18 * mm)
        canvas.setFont(FONT_BOLD, 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(width / 2, 10.8 * mm, SYNTHETIC_FOOTER)
        canvas.setFont(FONT, 6.3)
        canvas.drawString(18 * mm, 6.8 * mm, self.document_id)
        canvas.drawRightString(width - 18 * mm, 6.8 * mm, f"Pagina {doc.page}")
        canvas.restoreState()


def build_pdf(filename: str, document_id: str, title: str, story: list) -> None:
    DossierDocument(OUTPUT_DIR / filename, document_id=document_id, document_title=title).build(story)


def contract_story() -> list:
    story = title_block(
        "Contratto di consulenza professionale",
        "Servizi di cybersecurity - Progetto Mercury",
        [("Documento", "AUR-MER-CONS-2026-001"), ("Data", "12 febbraio 2026"), ("Decorrenza", "1 marzo 2026"), ("Classificazione", "Riservato - uso interno dimostrativo")],
    )
    story += [
        para("Tra <b>Aurora Sistemi S.r.l.</b>, con sede sintetica in Via delle Orbite 42, 20124 Milano (MI), di seguito \"Committente\", e il dott. <b>Marco Rossi</b>, consulente indipendente, di seguito \"Consulente\", si conviene quanto segue."),
        table(
            [
                ["Soggetto", "Informazioni contrattuali"],
                ["Committente", "Aurora Sistemi S.r.l. - referente di progetto: Giulia Bianchi"],
                ["Consulente", "Marco Rossi - consulente cybersecurity"],
                ["Domicilio professionale", "Via delle Nebulose 17, 00144 Roma (RM)"],
                ["Contatti", "marco.rossi@example.com - +39 320 000 4816"],
                ["Codice fiscale", MARCO_CF],
            ],
            [46 * mm, 128 * mm],
        ),
        section("1. Oggetto dell'incarico"),
        para("Il Committente affida al Consulente un incarico specialistico nell'ambito del <b>Progetto Mercury</b>. L'attività riguarda la revisione dell'architettura di sicurezza, la verifica delle configurazioni di accesso e la predisposizione delle evidenze tecniche necessarie al collaudo."),
        bullets(
            [
                "analisi del modello di minaccia e dei flussi applicativi rilevanti;",
                "revisione dei controlli di autenticazione, autorizzazione e segregazione dei ruoli;",
                "supporto alla gestione delle anomalie e redazione del rapporto tecnico conclusivo;",
                "partecipazione alle riunioni di avanzamento coordinate da Giulia Bianchi.",
            ]
        ),
        section("2. Durata e modalità di esecuzione"),
        para("L'incarico decorre dal 1 marzo 2026 e termina con l'accettazione del rapporto finale, prevista entro il 30 settembre 2026. Le attività sono svolte prevalentemente da remoto; gli accessi agli ambienti Mercury devono essere autorizzati e registrati."),
        PageBreak(),
        section("3. Corrispettivo"),
        callout("Il corrispettivo complessivo è stabilito in <b>€ 48.000,00</b>, oltre agli oneri fiscali applicabili. La fatturazione avviene in tre tranche collegate all'avvio, alla revisione intermedia e alla consegna finale."),
        para("Il pagamento è dovuto entro 30 giorni dalla ricezione di ciascuna fattura. Eventuali attività ulteriori devono essere approvate per iscritto dalla responsabile del progetto."),
        section("4. Riservatezza e protezione dei dati"),
        para("Marco Rossi tratta le informazioni ricevute esclusivamente per l'esecuzione dell'incarico. È vietata la copia su dispositivi personali non cifrati e la condivisione con soggetti non autorizzati. Ogni incidente o accesso anomalo deve essere comunicato senza ritardo ad Aurora Sistemi S.r.l."),
        section("5. Conservazione documentale"),
        callout("Il contratto, gli allegati amministrativi e le evidenze di accettazione sono conservati per <b>36 mesi</b> dalla chiusura del Progetto Mercury. Alla scadenza sono eliminati in modo verificabile, salvo legal hold o obbligo normativo documentato.", tone="amber"),
        section("6. Proprietà dei risultati"),
        para("I rapporti, le matrici di controllo e le configurazioni prodotte nell'incarico appartengono ad Aurora Sistemi S.r.l. Il Consulente conserva soltanto le informazioni necessarie alla gestione contabile del rapporto, nei limiti previsti dalla legge."),
        section("7. Recesso e chiusura"),
        para("Ciascuna parte può recedere con preavviso scritto di 15 giorni. Alla cessazione il Consulente restituisce o elimina i materiali Mercury e fornisce conferma scritta dell'avvenuta chiusura degli accessi."),
        Spacer(1, 8 * mm),
        signatures("Per Aurora Sistemi S.r.l. - Giulia Bianchi", "Il Consulente - Marco Rossi"),
    ]
    return story


def supplier_story() -> list:
    story = title_block(
        "Scheda anagrafica fornitore",
        "Northstar Analytics S.r.l.",
        [("Documento", "AUR-MER-FOR-2026-004"), ("Data verifica", "20 febbraio 2026"), ("Progetto", "Mercury"), ("Stato", "Qualificato - demo")],
    )
    story += [
        callout("Fornitore incaricato della <b>revisione dei dati</b> e dei controlli di qualità per il Progetto Mercury."),
        section("Anagrafica societaria"),
        key_value_table(
            [
                ("Ragione sociale", "Northstar Analytics S.r.l."),
                ("Sede legale", "Viale Polaris 18, 10121 Torino (TO)"),
                ("Partita IVA", NORTHSTAR_PIVA),
                ("PEC", "northstar.analytics@pec.example.com"),
                ("Telefono", "+39 011 0002716"),
                ("Sito dimostrativo", "northstar-analytics.example.com"),
            ]
        ),
        section("Referente operativo"),
        table(
            [
                ["Nome", "Ruolo", "Email", "Telefono"],
                ["Francesca Romano", "Responsabile data review", "francesca.romano@northstar-analytics.example.com", "+39 333 000 2716"],
            ],
            [31 * mm, 35 * mm, 79 * mm, 29 * mm],
        ),
        section("Coordinate di pagamento"),
        key_value_table(
            [
                ("Intestatario", "Northstar Analytics S.r.l."),
                ("Istituto", "Banca Dimostrativa S.p.A. - coordinate sintetiche"),
                ("IBAN", NORTHSTAR_IBAN_PRINT),
                ("Valuta", "EUR"),
            ]
        ),
        callout("L'IBAN e la Partita IVA sono costruiti deterministicamente e superano i rispettivi controlli formali. Non identificano un soggetto o un conto reale.", tone="amber"),
        PageBreak(),
        section("Perimetro della fornitura"),
        para("Northstar Analytics S.r.l. esegue la revisione del dataset Mercury, verifica completezza e coerenza dei campi e produce un verbale delle anomalie. Non assume responsabilità di project management e non può riutilizzare i dati per finalità proprie."),
        bullets(
            [
                "accesso limitato al workspace Mercury autorizzato;",
                "consegna delle osservazioni a Giulia Bianchi;",
                "coordinamento operativo con Marco Rossi per le verifiche di sicurezza;",
                "cancellazione delle copie di lavoro al termine della revisione.",
            ]
        ),
        section("Controlli di qualifica"),
        table(
            [
                ["Controllo", "Esito", "Evidenza"],
                ["Identità e recapiti", "Conforme", "Verifica documentale sintetica del 20/02/2026"],
                ["Accordo di riservatezza", "Conforme", "NDA-MER-NS-2026-01"],
                ["Misure di sicurezza", "Conforme con follow-up", "Questionario SEC-NS-04"],
                ["Coordinate di pagamento", "Conforme", "Validazione checksum completata"],
            ],
            [55 * mm, 38 * mm, 81 * mm],
        ),
        section("Approvazioni"),
        para("La scheda è approvata per l'utilizzo esclusivo nel Progetto Mercury. Ogni variazione di referente, sede o coordinate deve essere comunicata ad Aurora Sistemi S.r.l. prima dell'emissione di nuovi ordini."),
        Spacer(1, 7 * mm),
        signatures("Operations - Laura Conti", "Fornitore - Francesca Romano"),
    ]
    return story


def minutes_story() -> list:
    story = title_block(
        "Verbale di riunione",
        "Comitato di avanzamento - Progetto Mercury",
        [("Documento", "AUR-MER-VER-2026-006"), ("Data", "15 maggio 2026"), ("Orario", "10:00 - 11:20"), ("Modalità", "Videoconferenza")],
    )
    story += [
        section("Partecipanti"),
        table(
            [
                ["Partecipante", "Organizzazione", "Ruolo nella riunione"],
                ["Giulia Bianchi", "Aurora Sistemi S.r.l.", "Project owner e presidente"],
                ["Marco Rossi", "Consulente indipendente", "Cybersecurity"],
                ["Francesca Romano", "Northstar Analytics S.r.l.", "Responsabile data review"],
                ["Laura Conti", "Aurora Sistemi S.r.l.", "Operations e verbalizzazione"],
            ],
            [45 * mm, 60 * mm, 69 * mm],
        ),
        section("Sintesi esecutiva"),
        table(
            [
                ["Indicatore", "Valore approvato"],
                ["Budget complessivo", "€ 125.000,00"],
                ["Project owner", "Giulia Bianchi"],
                ["Consegna attesa", "30 settembre 2026"],
                ["Revisione dei dati", "Northstar Analytics S.r.l."],
            ],
            [62 * mm, 112 * mm],
        ),
        callout("Il comitato conferma il <b>budget di € 125.000,00</b>, la responsabilità di <b>Giulia Bianchi</b> e la consegna prevista per il <b>30 settembre 2026</b>."),
        PageBreak(),
        section("Andamento dei lavori"),
        para("Giulia Bianchi apre la riunione confermando che il Progetto Mercury procede secondo il perimetro approvato. Le attività di integrazione sono entrate nella fase di consolidamento e non risultano richieste di variazione sul budget."),
        para("Marco Rossi riferisce che la revisione degli accessi privilegiati è completata. Restano da chiudere due osservazioni di severità media relative alla rotazione delle credenziali di servizio; la verifica finale sarà inclusa nel rapporto di sicurezza."),
        para("Francesca Romano conferma che <b>Northstar Analytics S.r.l. svolge la revisione dei dati</b>. Il primo campione è coerente con il tracciato Mercury; alcune descrizioni devono essere uniformate prima del secondo passaggio di qualità."),
        section("Decisioni assunte"),
        table(
            [
                ["N.", "Decisione", "Responsabile", "Scadenza"],
                ["D-01", "Confermare il budget senza variazioni", "Giulia Bianchi", "Immediata"],
                ["D-02", "Chiudere le osservazioni sugli accessi", "Marco Rossi", "12 giugno 2026"],
                ["D-03", "Completare il secondo passaggio di data review", "Francesca Romano", "26 giugno 2026"],
                ["D-04", "Mantenere la data di consegna", "Comitato Mercury", "30 settembre 2026"],
            ],
            [15 * mm, 75 * mm, 49 * mm, 35 * mm],
        ),
        section("Azioni di follow-up"),
        bullets(
            [
                "Laura Conti aggiorna il registro delle decisioni e archivia il presente verbale;",
                "Marco Rossi invia l'evidenza della rotazione delle credenziali;",
                "Francesca Romano consegna l'elenco consolidato delle anomalie dati;",
                "Giulia Bianchi convoca il prossimo avanzamento per il 30 giugno 2026.",
            ]
        ),
        para("La riunione termina alle 11:20. Il verbale è considerato approvato se non pervengono osservazioni entro tre giorni lavorativi."),
        Spacer(1, 8 * mm),
        signatures("Project owner - Giulia Bianchi", "Verbalizzante - Laura Conti"),
    ]
    return story


def retention_story() -> list:
    story = title_block(
        "Policy interna",
        "Conservazione e cancellazione dei dati",
        [("Documento", "AUR-POL-RET-2026-002"), ("Versione", "1.0"), ("Efficacia", "1 marzo 2026"), ("Proprietario", "Funzione Governance")],
    )
    story += [
        callout("Questa policy definisce tempi uniformi, responsabilità e controlli per la conservazione delle informazioni aziendali. Le eccezioni devono essere motivate e tracciate."),
        section("1. Finalità e ambito"),
        para("La policy si applica ai documenti e ai log gestiti nei sistemi di Aurora Sistemi S.r.l., inclusi i workspace di progetto. L'obiettivo è limitare la conservazione al periodo necessario, mantenendo evidenze verificabili delle operazioni di cancellazione."),
        section("2. Principi operativi"),
        bullets(
            [
                "minimizzazione: conservare solo informazioni pertinenti alla finalità dichiarata;",
                "limitazione temporale: applicare la scadenza dalla data di chiusura dell'attività;",
                "verificabilità: registrare esito, data e responsabile della cancellazione;",
                "sospensione controllata: interrompere la cancellazione in presenza di legal hold attivo.",
            ]
        ),
        section("3. Matrice di conservazione"),
        table(
            [
                ["Categoria", "Periodo", "Evento iniziale", "Trattamento a scadenza"],
                ["Documenti contrattuali", "36 mesi", "Chiusura del contratto o progetto", "Cancellazione verificata"],
                ["Documenti tecnici", "18 mesi", "Accettazione della versione finale", "Cancellazione o anonimizzazione"],
                ["Log operativi", "90 giorni", "Data di generazione del log", "Rotazione automatica"],
            ],
            [49 * mm, 27 * mm, 55 * mm, 43 * mm],
        ),
        callout("Periodi obbligatori: <b>36 mesi</b> per i documenti contrattuali, <b>18 mesi</b> per i documenti tecnici e <b>90 giorni</b> per i log operativi.", tone="amber"),
        PageBreak(),
        section("4. Procedura di cancellazione"),
        para("Il sistema individua gli elementi scaduti e produce un elenco di verifica. Prima dell'esecuzione devono essere controllati legal hold, dipendenze audit e copie presenti nello storage. La cancellazione è completata soltanto quando sorgente, dati derivati e mapping reversibili risultano rimossi."),
        para("La ricevuta di cancellazione contiene identificativo tecnico, workspace, data, esito e soggetto che ha autorizzato l'operazione. Non deve contenere il nome del file, il contenuto o identificatori personali estratti."),
        section("5. Legal hold ed eccezioni"),
        para("Un legal hold sospende ogni cancellazione per il perimetro indicato. La sospensione deve riportare motivo, responsabile e data di revisione. Alla chiusura del legal hold il calcolo della scadenza riprende secondo la decisione documentata dalla funzione Governance."),
        section("6. Ruoli e controlli"),
        table(
            [
                ["Ruolo", "Responsabilità"],
                ["Owner del dato", "Classifica l'informazione e conferma l'evento iniziale"],
                ["Operations", "Esegue i job di retention e verifica lo storage"],
                ["Governance", "Approva policy, eccezioni e legal hold"],
                ["Audit", "Verifica campioni di cancellazione e integrità delle ricevute"],
            ],
            [49 * mm, 125 * mm],
        ),
        section("7. Riesame"),
        para("La policy è riesaminata almeno annualmente o in occasione di modifiche normative, tecnologiche o organizzative rilevanti. Ogni nuova versione sostituisce la precedente mantenendo lo storico delle approvazioni."),
        Spacer(1, 8 * mm),
        signatures("Approvazione Governance", "Presa in carico Operations"),
    ]
    return story


def incident_story() -> list:
    story = title_block(
        "Segnalazione interna di incidente",
        "Accesso anomalo al workspace Mercury",
        [("Documento", "AUR-MER-INC-2026-014"), ("Data evento", "18 giugno 2026"), ("Apertura", "18 giugno 2026 - 08:42"), ("Severità", "Media - contenuta")],
    )
    story += [
        callout("L'evento è stato contenuto alle 10:18. Non sono emerse evidenze di esfiltrazione; la revisione tecnica rimane aperta fino alla chiusura delle azioni correttive."),
        section("Descrizione dell'evento"),
        para("Alle 08:42 del 18 giugno 2026, <b>Laura Conti</b> ha ricevuto su laura.conti@aurora-sistemi.example.com una notifica del sistema di monitoraggio relativa a tre tentativi di accesso al workspace del <b>Progetto Mercury</b>. Gli eventi provenivano da un dispositivo non riconosciuto e utilizzavano un account tecnico destinato alle attività di integrazione."),
        para("Laura ha inoltrato la segnalazione alla casella soc@aurora-sistemi.example.com e ha avvisato telefonicamente <b>Giulia Bianchi</b> al numero +39 333 000 1842. Giulia, in qualità di responsabile del progetto, ha chiesto la sospensione temporanea dell'account e l'apertura del registro di incidente AUR-MER-INC-2026-014."),
        subsection("Prima analisi"),
        para("Alle 08:57 è stato contattato <b>Marco Rossi</b> all'indirizzo marco.rossi@example.com e al numero +39 320 000 4816. Marco ha verificato i log di autenticazione e ha rilevato che i tentativi non avevano superato il secondo fattore. L'ultimo evento anomalo risultava registrato alle 08:39; non erano presenti download o modifiche ai documenti."),
        para("Alle 09:18 Giulia Bianchi ha informato <b>Francesca Romano</b>, referente di <b>Northstar Analytics S.r.l.</b>, tramite francesca.romano@northstar-analytics.example.com. Francesca ha confermato che il gruppo incaricato della revisione dei dati non aveva avviato sessioni prima delle 09:00 e ha sospeso in via prudenziale il proprio accesso al workspace."),
        subsection("Contenimento"),
        para("Tra le 09:25 e le 10:05 Marco Rossi ha invalidato il token dell'account tecnico, ruotato la credenziale e confrontato gli indirizzi di origine con l'elenco autorizzato. Il controllo ha ricondotto l'anomalia a una configurazione rimasta attiva su una macchina di collaudo dismessa, senza evidenze di utilizzo da parte di terzi."),
        para("Alle 10:18 il servizio è stato riattivato con una nuova credenziale e con una regola più restrittiva. Laura Conti ha aggiornato il registro operativo e ha comunicato la chiusura del contenimento a Giulia Bianchi al numero +39 333 000 1842."),
        PageBreak(),
        section("Valutazione e impatto"),
        para("L'incidente è classificato di severità media per l'uso improprio di una credenziale ancora valida. L'impatto osservato è limitato ai tentativi di autenticazione: non risultano accessi completati, alterazioni dei dati o trasferimenti verso l'esterno. Northstar Analytics effettuerà comunque un controllo incrociato sul campione dati Mercury."),
        section("Azioni concordate"),
        bullets(
            [
                "Marco Rossi completa entro il 20 giugno 2026 la verifica di tutte le credenziali di servizio;",
                "Laura Conti aggiorna l'inventario delle macchine di collaudo e rimuove le configurazioni obsolete;",
                "Francesca Romano documenta l'esito della revisione dati entro il 23 giugno 2026;",
                "Giulia Bianchi riesamina l'incidente nel comitato Mercury del 30 giugno 2026.",
            ]
        ),
        section("Chiusura provvisoria"),
        para("La segnalazione resta in monitoraggio fino al completamento delle azioni. Qualsiasi nuovo accesso anomalo deve essere comunicato immediatamente a soc@aurora-sistemi.example.com citando il riferimento AUR-MER-INC-2026-014."),
        Spacer(1, 8 * mm),
        signatures("Segnalante - Laura Conti", "Project owner - Giulia Bianchi"),
    ]
    return story


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    documents = [
        ("01_contratto_consulenza_marco_rossi.pdf", "AUR-MER-CONS-2026-001", "Contratto di consulenza - Marco Rossi", contract_story()),
        ("02_scheda_fornitore_northstar_analytics.pdf", "AUR-MER-FOR-2026-004", "Scheda fornitore - Northstar Analytics", supplier_story()),
        ("03_verbale_progetto_mercury.pdf", "AUR-MER-VER-2026-006", "Verbale Progetto Mercury", minutes_story()),
        ("04_policy_conservazione_dati.pdf", "AUR-POL-RET-2026-002", "Policy di conservazione dei dati", retention_story()),
        ("05_segnalazione_incidente.pdf", "AUR-MER-INC-2026-014", "Segnalazione incidente Mercury", incident_story()),
    ]
    for filename, document_id, title, story in documents:
        build_pdf(filename, document_id, title, story)
        print(f"generated {filename}")
    print(f"synthetic identifiers: CF={MARCO_CF} PIVA={NORTHSTAR_PIVA} IBAN={NORTHSTAR_IBAN}")


if __name__ == "__main__":
    main()
