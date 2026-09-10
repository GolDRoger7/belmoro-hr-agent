"""
Layer di data cleaning DETERMINISTICO applicato al dataset HR prima di
consegnarlo all'agente pandas.

Scelta architetturale
---------------------
La pulizia avviene su due livelli:

 1) questo modulo, che applica in modo riproducibile e verificabile le
    correzioni note del dataset (formati data misti, separatori decimali,
    categorie incoerenti, duplicati, valori fuori range) e produce un
    REPORT ispezionabile;
 2) l'agente LLM, che sul dataframe già normalizzato decide caso per caso come
    trattare i valori mancanti residui (escluderli, imputarli con la mediana,
    segnalarli) in funzione della domanda dell'utente.

Il primo livello garantisce determinismo e ripetibilità delle analisi; il
secondo garantisce l'adattabilità richiesta a un agente.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

# --- Range di validità di dominio (dalle policy HR aziendali) ---------------
RANGE_VALIDI = {
    "eta": (18, 70),
    "performance_rating": (1, 5),
    "engagement_score": (0, 100),
    "giorni_smart_working_mese": (0, 22),
    "giorni_ferie_residui": (0, 60),
    "giorni_assenza_anno": (0, 365),
    "ore_formazione_anno": (0, 400),
    "anzianita_anni": (0, 45),
    "ral_annua_eur": (10_000, 400_000),
    "bonus_annuo_eur": (0, 200_000),
}

FORMATI_DATA = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]

COLONNE_DATA = ["data_nascita", "data_assunzione", "data_cessazione"]

VALORI_NULLI = {"", " ", "n/d", "N/D", "nd", "NULL", "null", "None", "none", "-", "NaN", "nan"}


def _to_number(valore: Any) -> float:
    """
    Converte in float un importo scritto in formati eterogenei:
    "45000", "45000.00", "45.000,00", "EUR 45000", "€ 45000", "" -> NaN
    """
    if valore is None or (isinstance(valore, float) and np.isnan(valore)):
        return np.nan
    if isinstance(valore, (int, float)):
        return float(valore)

    testo = str(valore).strip()
    if testo in VALORI_NULLI:
        return np.nan

    # rimuove valuta, spazi e caratteri non numerici di contorno
    testo = re.sub(r"(?i)(eur|€|\$)", "", testo).strip()
    testo = testo.replace(" ", "").replace(" ", "")

    if "," in testo and "." in testo:
        # formato italiano "45.000,00": il punto è separatore di migliaia
        testo = testo.replace(".", "").replace(",", ".")
    elif "," in testo:
        # "45000,50" -> decimale ; "45,000" -> migliaia
        testo = testo.replace(",", ".") if re.search(r",\d{1,2}$", testo) else testo.replace(",", "")
    elif "." in testo:
        # "45.000" (migliaia) vs "45000.00" (decimale)
        if re.search(r"\.\d{3}$", testo) and not re.search(r"\.\d{1,2}$", testo):
            testo = testo.replace(".", "")

    try:
        return float(testo)
    except ValueError:
        return np.nan


def _parse_data(serie: pd.Series) -> pd.Series:
    """Prova in cascata i formati data presenti nel sorgente."""
    risultato = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
    testo = serie.astype("string").str.strip()
    testo = testo.where(~testo.isin(VALORI_NULLI), other=pd.NA)

    for fmt in FORMATI_DATA:
        mancanti = risultato.isna() & testo.notna()
        if not mancanti.any():
            break
        parsed = pd.to_datetime(testo[mancanti], format=fmt, errors="coerce")
        risultato.loc[mancanti] = parsed
    return risultato


def clean_dataframe(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Restituisce (dataframe pulito, report della pulizia)."""
    report: dict[str, Any] = {
        "righe_iniziali": int(len(df_raw)),
        "colonne_iniziali": int(df_raw.shape[1]),
        "operazioni": [],
        "valori_mancanti_residui": {},
    }
    df = df_raw.copy()

    # ---------------------------------------------------------------- 1. trim
    colonne_testo = [c for c in df.columns if pd.api.types.is_string_dtype(df[c])]
    for col in colonne_testo:
        df[col] = df[col].astype("string").str.strip()
    df = df.replace(list(VALORI_NULLI), pd.NA)
    report["operazioni"].append(
        f"Rimossi spazi superflui da {len(colonne_testo)} colonne testuali e normalizzati i marcatori di valore nullo (''/'NULL'/'n/d')."
    )

    # --------------------------------------------------------- 2. duplicati
    prima = len(df)
    df = df.drop_duplicates()
    dup_esatti = prima - len(df)

    prima = len(df)
    df = df.drop_duplicates(subset=["id_dipendente"], keep="first")
    dup_id = prima - len(df)
    report["duplicati_rimossi"] = int(dup_esatti + dup_id)
    report["operazioni"].append(
        f"Rimosse {dup_esatti} righe interamente duplicate e {dup_id} ulteriori duplicati su id_dipendente."
    )

    # ------------------------------------------------- 3. categorie coerenti
    if "dipartimento" in df:
        mappa_dip = {
            "produzione": "Produzione", "supply chain": "Supply Chain", "vendite": "Vendite",
            "marketing": "Marketing", "r&d": "R&D", "it": "IT", "finance": "Finance",
            "customer care": "Customer Care", "people & culture": "People & Culture",
        }
        df["dipartimento"] = df["dipartimento"].astype("string").str.strip().str.lower().map(mappa_dip)

    if "genere" in df:
        mappa_gen = {"m": "M", "maschio": "M", "f": "F", "femmina": "F", "altro": "Altro"}
        df["genere"] = df["genere"].astype("string").str.strip().str.lower().map(mappa_gen)

    if "stato" in df:
        df["stato"] = df["stato"].astype("string").str.strip().str.capitalize()
        df["stato"] = df["stato"].where(df["stato"].isin(["Attivo", "Cessato"]), pd.NA)

    if "tipo_contratto" in df:
        df["tipo_contratto"] = df["tipo_contratto"].astype("string").str.strip().str.title()

    if "livello_inquadramento" in df:
        df["livello_inquadramento"] = df["livello_inquadramento"].astype("string").str.strip().str.title()

    report["operazioni"].append(
        "Uniformate le categorie di dipartimento, genere, stato, tipo di contratto e livello (maiuscole/minuscole e spazi incoerenti)."
    )

    # ---------------------------------------------------- 4. colonne numeriche
    fuori_range: dict[str, int] = {}
    for col, (minimo, massimo) in RANGE_VALIDI.items():
        if col not in df.columns:
            continue
        df[col] = df[col].map(_to_number)
        maschera = df[col].notna() & ((df[col] < minimo) | (df[col] > massimo))
        n_fuori = int(maschera.sum())
        if n_fuori:
            fuori_range[col] = n_fuori
        df.loc[maschera, col] = np.nan

    report["valori_fuori_range_azzerati"] = fuori_range
    if fuori_range:
        dettaglio = ", ".join(f"{k}: {v}" for k, v in fuori_range.items())
        report["operazioni"].append(
            f"Convertite le colonne numeriche (valuta e separatori decimali misti) e portati a valore mancante i dati fuori dai range di dominio -> {dettaglio}."
        )

    # ------------------------------------------------------------- 5. date
    for col in COLONNE_DATA:
        if col in df.columns:
            df[col] = _parse_data(df[col])
    report["operazioni"].append(
        "Normalizzate le date scritte in 4 formati diversi (ISO, gg/mm/aaaa, gg-mm-aaaa, gg.mm.aaaa) in veri datetime."
    )

    # ------------------------------------------- 6. colonne derivate utili
    if "data_assunzione" in df:
        df["anno_assunzione"] = df["data_assunzione"].dt.year
    if "data_cessazione" in df:
        df["anno_cessazione"] = df["data_cessazione"].dt.year
        df["mese_cessazione"] = df["data_cessazione"].dt.to_period("M").astype("string")
    if "stato" in df:
        df["is_cessato"] = (df["stato"] == "Cessato").astype("int8")
    if {"data_assunzione", "data_cessazione"}.issubset(df.columns):
        durata = (df["data_cessazione"] - df["data_assunzione"]).dt.days / 365.25
        df["durata_rapporto_anni"] = durata.round(2)
    report["operazioni"].append(
        "Aggiunte colonne derivate: anno_assunzione, anno_cessazione, mese_cessazione, is_cessato, durata_rapporto_anni."
    )

    # ------------------------------- 7. coerenza logica stato / data uscita
    if {"stato", "data_cessazione"}.issubset(df.columns):
        incoerenti = int(((df["stato"] == "Attivo") & df["data_cessazione"].notna()).sum())
        if incoerenti:
            df.loc[df["stato"] == "Attivo", "data_cessazione"] = pd.NaT
            report["operazioni"].append(
                f"Corrette {incoerenti} righe con stato 'Attivo' ma data di cessazione valorizzata."
            )

    # --------------------------------------------------------- 8. report NA
    residui = df.isna().sum()
    report["valori_mancanti_residui"] = {
        col: int(n) for col, n in residui.items() if n > 0
    }
    report["righe_finali"] = int(len(df))
    report["colonne_finali"] = int(df.shape[1])

    return df, report


def riassunto_testuale(report: dict) -> str:
    """Versione leggibile del report, usata nel prompt dell'agente e in risposta."""
    righe = [
        f"Righe lette dal CSV: {report['righe_iniziali']} -> righe dopo la pulizia: {report['righe_finali']}",
        f"Duplicati rimossi: {report.get('duplicati_rimossi', 0)}",
    ]
    righe += [f"- {op}" for op in report["operazioni"]]
    if report.get("valori_mancanti_residui"):
        top = sorted(report["valori_mancanti_residui"].items(), key=lambda x: -x[1])[:8]
        righe.append(
            "Valori mancanti residui (da gestire in analisi): "
            + ", ".join(f"{c}={n}" for c, n in top)
        )
    return "\n".join(righe)
