"""
Generatore del dataset HR sintetico per il caso d'uso
"Caffè Belmoro S.p.A. - People & Culture" (azienda e dati FITTIZI, a scopo didattico).

Il dataset viene generato con anomalie realistiche e volute:
  - valori mancanti (NaN / stringhe vuote)
  - righe duplicate
  - formati data incoerenti (ISO, italiano con / e con -)
  - separatori decimali misti e simboli di valuta nella RAL
  - categorie scritte in modo incoerente ("Vendite", "vendite", " VENDITE ")
  - valori fuori range (performance = 7, eta negativa, RAL assurde)

Uso:  python3 data/genera_dataset.py
"""

import csv
import random
import unicodedata
from datetime import date, timedelta

random.seed(42)

N_RIGHE = 1240          # >= 1000 come da requisito
N_DUPLICATI = 45        # righe duplicate iniettate
OUTPUT = "data/hr_dipendenti_belmoro.csv"

NOMI_M = ["Marco", "Luca", "Andrea", "Giuseppe", "Francesco", "Alessandro", "Matteo",
          "Davide", "Simone", "Stefano", "Riccardo", "Fabio", "Paolo", "Giovanni",
          "Antonio", "Lorenzo", "Federico", "Nicola", "Emanuele", "Gabriele"]
NOMI_F = ["Giulia", "Chiara", "Sara", "Martina", "Francesca", "Elena", "Alessia",
          "Valentina", "Silvia", "Laura", "Anna", "Ilaria", "Federica", "Marta",
          "Beatrice", "Serena", "Camilla", "Roberta", "Elisa", "Cristina"]
COGNOMI = ["Rossi", "Ferrari", "Russo", "Bianchi", "Romano", "Gallo", "Costa", "Conti",
           "Esposito", "Ricci", "Bruno", "Greco", "Marino", "Rizzo", "Moretti",
           "Barbieri", "Fontana", "Santoro", "Mariani", "Rinaldi", "Caruso", "Ferrara",
           "Galli", "Martini", "Leone", "Longo", "Gentile", "Martinelli", "Vitale",
           "Lombardi", "Serra", "Coppola", "De Luca", "Villa", "Sartori", "Pellegrini"]

# dipartimento -> (peso, sedi tipiche, media smart working, rischio turnover)
DIPARTIMENTI = {
    "Produzione":     {"peso": 26, "sw": 0.5, "turnover": 0.09},
    "Supply Chain":   {"peso": 11, "sw": 5.0, "turnover": 0.11},
    "Vendite":        {"peso": 16, "sw": 8.0, "turnover": 0.21},
    "Marketing":      {"peso": 9,  "sw": 9.0, "turnover": 0.13},
    "R&D":            {"peso": 8,  "sw": 7.0, "turnover": 0.07},
    "IT":             {"peso": 10, "sw": 11.0, "turnover": 0.18},
    "Finance":        {"peso": 7,  "sw": 8.0, "turnover": 0.08},
    "Customer Care":  {"peso": 8,  "sw": 9.5, "turnover": 0.24},
    "People & Culture": {"peso": 5, "sw": 8.0, "turnover": 0.10},
}

SEDI = {
    "Produzione":       [("Rivalta", 45), ("Novara", 20), ("Caserta", 20), ("Aosta", 15)],
    "Supply Chain":     [("Rivalta", 40), ("Torino", 35), ("Milano", 25)],
    "Vendite":          [("Torino", 30), ("Milano", 35), ("Roma", 20), ("Londra", 15)],
    "Marketing":        [("Torino", 45), ("Milano", 35), ("Londra", 20)],
    "R&D":              [("Torino", 70), ("Rivalta", 30)],
    "IT":               [("Torino", 55), ("Milano", 30), ("Remoto", 15)],
    "Finance":          [("Torino", 60), ("Milano", 40)],
    "Customer Care":    [("Torino", 50), ("Milano", 25), ("Remoto", 25)],
    "People & Culture": [("Torino", 70), ("Milano", 30)],
}

LIVELLI = [("Operaio", 34), ("Impiegato", 44), ("Quadro", 17), ("Dirigente", 5)]
RAL_BASE = {"Operaio": 27000, "Impiegato": 38000, "Quadro": 62000, "Dirigente": 108000}

CONTRATTI = [("Indeterminato", 74), ("Determinato", 12), ("Apprendistato", 9), ("Stage", 5)]

MOTIVI_USCITA = ["Dimissioni volontarie", "Migliore offerta esterna", "Trasferimento geografico",
                 "Fine contratto", "Pensionamento", "Risoluzione consensuale", "Licenziamento"]

TITOLI = ["Diploma", "Laurea Triennale", "Laurea Magistrale", "Master", "Dottorato"]


def scelta_pesata(coppie):
    valori = [v for v, _ in coppie]
    pesi = [p for _, p in coppie]
    return random.choices(valori, weights=pesi, k=1)[0]


def slugify(testo):
    testo = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return testo.lower().replace(" ", "").replace("'", "")


def data_casuale(inizio, fine):
    delta = (fine - inizio).days
    return inizio + timedelta(days=random.randint(0, delta))


def formatta_data(d, stile):
    """Formati volutamente incoerenti per costringere l'agente al data cleaning."""
    if stile == 0:
        return d.isoformat()                       # 2019-03-14
    if stile == 1:
        return d.strftime("%d/%m/%Y")              # 14/03/2019
    if stile == 2:
        return d.strftime("%d-%m-%Y")              # 14-03-2019
    return d.strftime("%d.%m.%Y")                  # 14.03.2019


def formatta_ral(valore, stile):
    """Separatori decimali e valuta incoerenti."""
    if stile == 0:
        return str(int(valore))                    # 45000
    if stile == 1:
        return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # 45.000,00
    if stile == 2:
        return f"EUR {int(valore)}"                # EUR 45000
    if stile == 3:
        return f"{valore:.2f}"                     # 45000.00
    return f"€ {int(valore)}"                      # € 45000


OGGI = date(2025, 12, 31)
righe = []

for i in range(1, N_RIGHE + 1):
    genere_reale = random.choices(["M", "F", "Altro"], weights=[52, 46, 2], k=1)[0]
    nome = random.choice(NOMI_M if genere_reale == "M" else NOMI_F)
    cognome = random.choice(COGNOMI)

    dip = scelta_pesata([(k, v["peso"]) for k, v in DIPARTIMENTI.items()])
    sede = scelta_pesata(SEDI[dip])
    livello = scelta_pesata(LIVELLI)
    contratto = scelta_pesata(CONTRATTI)
    titolo = random.choice(TITOLI)

    eta = int(random.gauss(41, 9))
    eta = max(21, min(64, eta))
    data_nascita = date(OGGI.year - eta, random.randint(1, 12), random.randint(1, 28))

    max_anni = min(25, eta - 20)
    anzianita = round(min(max_anni, abs(random.gauss(6, 5)) + 0.3), 1)
    data_assunzione = OGGI - timedelta(days=int(anzianita * 365.25))

    # --- Retribuzione: base per livello + anzianita + seniority + rumore ---
    base = RAL_BASE[livello]
    ral = base * (1 + 0.021 * anzianita) * random.gauss(1.0, 0.11)
    if dip in ("IT", "R&D", "Finance"):
        ral *= 1.07
    if dip in ("Customer Care", "Produzione"):
        ral *= 0.95
    if sede == "Londra":
        ral *= 1.22
    # gender pay gap realistico (~6-8%) volutamente presente per l'analisi
    if genere_reale == "F":
        ral *= random.uniform(0.90, 0.97)
    ral = round(ral, 2)

    bonus_pct = {"Operaio": 0.02, "Impiegato": 0.05, "Quadro": 0.12, "Dirigente": 0.22}[livello]
    bonus = round(ral * bonus_pct * random.uniform(0.4, 1.6), 2)

    # --- Performance ed engagement (correlati fra loro) ---
    perf = random.choices([1, 2, 3, 4, 5], weights=[3, 12, 42, 32, 11], k=1)[0]
    engagement = int(min(100, max(10, random.gauss(45 + perf * 9, 11))))
    if dip in ("Customer Care", "Vendite"):
        engagement = max(10, engagement - random.randint(3, 12))

    sw_medio = DIPARTIMENTI[dip]["sw"]
    if sede == "Remoto":
        sw_medio = 18
    smart_working = int(max(0, min(20, random.gauss(sw_medio, 2.5))))

    ore_formazione = int(max(0, random.gauss(26 + perf * 3, 12)))
    ferie_residui = int(max(0, min(45, random.gauss(11, 6))))
    assenze = int(max(0, random.gauss(7 - perf * 0.5, 4)))

    # --- Turnover: guidato da dipartimento, performance, engagement, contratto ---
    p_turnover = DIPARTIMENTI[dip]["turnover"]
    if perf <= 2:
        p_turnover += 0.14
    if engagement < 45:
        p_turnover += 0.12
    if contratto in ("Determinato", "Stage"):
        p_turnover += 0.20
    if smart_working <= 1 and dip not in ("Produzione",):
        p_turnover += 0.06
    cessato = random.random() < min(0.72, p_turnover)

    if cessato:
        stato = "Cessato"
        giorni_max = max(30, int(anzianita * 365.25))
        data_uscita = data_assunzione + timedelta(days=random.randint(30, giorni_max))
        if data_uscita > OGGI:
            data_uscita = OGGI - timedelta(days=random.randint(1, 200))
        motivo = random.choice(MOTIVI_USCITA)
    else:
        stato = "Attivo"
        data_uscita = None
        motivo = ""

    stile_data = random.choices([0, 1, 2, 3], weights=[62, 22, 11, 5], k=1)[0]
    stile_ral = random.choices([0, 1, 2, 3, 4], weights=[64, 14, 8, 9, 5], k=1)[0]

    riga = {
        "id_dipendente": f"EMP-{i:05d}",
        "nome": nome,
        "cognome": cognome,
        "email": f"{slugify(nome)}.{slugify(cognome)}@belmoro-demo.it",
        "genere": genere_reale,
        "eta": eta,
        "data_nascita": data_nascita.isoformat(),
        "data_assunzione": formatta_data(data_assunzione, stile_data),
        "data_cessazione": formatta_data(data_uscita, stile_data) if data_uscita else "",
        "dipartimento": dip,
        "sede": sede,
        "livello_inquadramento": livello,
        "tipo_contratto": contratto,
        "titolo_studio": titolo,
        "anzianita_anni": anzianita,
        "ral_annua_eur": formatta_ral(ral, stile_ral),
        "bonus_annuo_eur": round(bonus, 2),
        "performance_rating": perf,
        "engagement_score": engagement,
        "ore_formazione_anno": ore_formazione,
        "giorni_smart_working_mese": smart_working,
        "giorni_ferie_residui": ferie_residui,
        "giorni_assenza_anno": assenze,
        "stato": stato,
        "motivo_cessazione": motivo,
    }
    righe.append(riga)

# =====================================================================
# INIEZIONE DELLE ANOMALIE ("dati sporchi")
# =====================================================================

def campiona(percentuale):
    k = int(len(righe) * percentuale)
    return random.sample(range(len(righe)), k)

# 1) valori mancanti
for idx in campiona(0.045):
    righe[idx]["ral_annua_eur"] = ""
for idx in campiona(0.038):
    righe[idx]["performance_rating"] = ""
for idx in campiona(0.030):
    righe[idx]["engagement_score"] = ""
for idx in campiona(0.025):
    righe[idx]["giorni_smart_working_mese"] = ""
for idx in campiona(0.020):
    righe[idx]["email"] = ""
for idx in campiona(0.018):
    righe[idx]["titolo_studio"] = "n/d"
for idx in campiona(0.015):
    righe[idx]["sede"] = "NULL"

# 2) categorie scritte in modo incoerente
for idx in campiona(0.07):
    righe[idx]["dipartimento"] = random.choice([
        righe[idx]["dipartimento"].upper(),
        righe[idx]["dipartimento"].lower(),
        f"  {righe[idx]['dipartimento']} ",
    ])
for idx in campiona(0.06):
    g = righe[idx]["genere"]
    righe[idx]["genere"] = {"M": random.choice(["m", "Maschio", "MASCHIO"]),
                            "F": random.choice(["f", "Femmina", "FEMMINA"]),
                            "Altro": "altro"}[g]
for idx in campiona(0.04):
    righe[idx]["stato"] = righe[idx]["stato"].lower()
for idx in campiona(0.03):
    righe[idx]["tipo_contratto"] = righe[idx]["tipo_contratto"].upper()

# 3) valori fuori range / impossibili
for idx in campiona(0.012):
    righe[idx]["performance_rating"] = random.choice([0, 6, 7, -1])
for idx in campiona(0.008):
    righe[idx]["eta"] = random.choice([-5, 0, 129, 17])
for idx in campiona(0.006):
    righe[idx]["ral_annua_eur"] = random.choice(["-32000", "9999999", "0", "N/D"])
for idx in campiona(0.010):
    righe[idx]["giorni_smart_working_mese"] = random.choice([31, 45, -3])
for idx in campiona(0.008):
    righe[idx]["giorni_assenza_anno"] = random.choice([400, -2])
for idx in campiona(0.007):
    righe[idx]["engagement_score"] = random.choice([150, -10])

# 4) spazi sporchi negli identificativi e nei nomi
for idx in campiona(0.03):
    righe[idx]["cognome"] = f" {righe[idx]['cognome']}  "
for idx in campiona(0.02):
    righe[idx]["id_dipendente"] = f"{righe[idx]['id_dipendente']} "

# 5) incoerenza logica: cessati senza motivo / attivi con data cessazione
for idx in campiona(0.02):
    if righe[idx]["stato"].lower() == "cessato":
        righe[idx]["motivo_cessazione"] = ""

# 6) righe duplicate
for idx in random.sample(range(len(righe)), N_DUPLICATI):
    righe.append(dict(righe[idx]))
random.shuffle(righe)

# =====================================================================
# SCRITTURA CSV
# =====================================================================
colonne = list(righe[0].keys())
with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=colonne)
    writer.writeheader()
    writer.writerows(righe)

print(f"Dataset generato: {OUTPUT}")
print(f"Righe totali: {len(righe)} (di cui {N_DUPLICATI} duplicati iniettati)")
print(f"Colonne: {len(colonne)} -> {', '.join(colonne)}")
