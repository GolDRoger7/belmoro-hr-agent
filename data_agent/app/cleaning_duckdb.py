"""
Pulizia del dataset eseguita INTERAMENTE dentro DuckDB.

Perché non basta leggere da DuckDB
----------------------------------
La prima versione dello store materializzava comunque il CSV in un DataFrame
pandas per ripulirlo, e solo dopo lo scriveva nella tabella: il picco di memoria
restava proporzionale alla dimensione del file, cioè il problema che lo store
doveva risolvere.

Qui la normalizzazione è una query. DuckDB legge il CSV in streaming con
`read_csv`, applica trasformazioni e scarti, e scrive direttamente la tabella:
in nessun momento il file esiste per intero nella memoria del processo Python.
Il costo è che le regole di dominio vanno espresse in SQL invece che in pandas;
il guadagno è che la stessa pipeline regge un file da centinaia di migliaia di
righe senza cambiare una riga di codice.

La corrispondenza con l'implementazione pandas di riferimento
(`data_cleaning.py`) è verificata colonna per colonna dal test di parità
`tests/test_parita_pulizia.py`: se le due divergono, il test fallisce.
"""

from __future__ import annotations

import duckdb

from .data_cleaning import COLONNE_DATA, RANGE_VALIDI, VALORI_NULLI

# Mappe di normalizzazione delle categorie (identiche a quelle pandas)
MAPPA_DIPARTIMENTO = {
    "produzione": "Produzione", "supply chain": "Supply Chain", "vendite": "Vendite",
    "marketing": "Marketing", "r&d": "R&D", "it": "IT", "finance": "Finance",
    "customer care": "Customer Care", "people & culture": "People & Culture",
}
MAPPA_GENERE = {"m": "M", "maschio": "M", "f": "F", "femmina": "F", "altro": "Altro"}

COLONNE_TITLE_CASE = ("tipo_contratto", "livello_inquadramento")

# Formati data accettati, provati nell'ordine
FORMATI_DATA_SQL = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y")


def _letterale(valore: str) -> str:
    return "'" + valore.replace("'", "''") + "'"


def _mappa_sql(colonna: str, mappa: dict[str, str]) -> str:
    """CASE ... WHEN che riproduce `Series.str.lower().map(mappa)`."""
    rami = "\n        ".join(
        f"WHEN lower({colonna}) = {_letterale(chiave)} THEN {_letterale(valore)}"
        for chiave, valore in mappa.items()
    )
    return f"CASE\n        {rami}\n        ELSE NULL\n      END"


def definisci_macro(con: duckdb.DuckDBPyConnection) -> None:
    """Registra le funzioni di normalizzazione usate dalla query di pulizia."""
    marcatori = ", ".join(_letterale(v) for v in sorted(VALORI_NULLI))

    # Testo: spazi tolti e marcatori di nullo riconosciuti ('', 'NULL', 'n/d'...)
    con.execute(f"""
        CREATE OR REPLACE TEMP MACRO pulisci_testo(v) AS
          CASE WHEN trim(coalesce(v, '')) IN ({marcatori}) THEN NULL ELSE trim(v) END
    """)

    # Importo: via valuta e spazi (anche quello unificatore), poi separatori misti
    con.execute(r"""
        CREATE OR REPLACE TEMP MACRO _senza_valuta(v) AS
          nullif(
            replace(
              replace(
                regexp_replace(coalesce(v, ''), '(?i)(eur|€|\$)', '', 'g'),
              ' ', ''),
            chr(160), ''),
          '')
    """)
    con.execute(r"""
        CREATE OR REPLACE TEMP MACRO a_numero(v) AS
          try_cast(
            CASE
              WHEN _senza_valuta(v) IS NULL THEN NULL
              -- "45.000,00": il punto separa le migliaia, la virgola i decimali
              WHEN contains(_senza_valuta(v), ',') AND contains(_senza_valuta(v), '.')
                THEN replace(replace(_senza_valuta(v), '.', ''), ',', '.')
              -- "45000,50": virgola decimale
              WHEN contains(_senza_valuta(v), ',') AND regexp_matches(_senza_valuta(v), ',\d{1,2}$')
                THEN replace(_senza_valuta(v), ',', '.')
              -- "45,000": virgola di migliaia
              WHEN contains(_senza_valuta(v), ',')
                THEN replace(_senza_valuta(v), ',', '')
              -- "45.000": punto di migliaia (tre cifre finali, non due decimali)
              WHEN contains(_senza_valuta(v), '.')
                   AND regexp_matches(_senza_valuta(v), '\.\d{3}$')
                   AND NOT regexp_matches(_senza_valuta(v), '\.\d{1,2}$')
                THEN replace(_senza_valuta(v), '.', '')
              ELSE _senza_valuta(v)
            END AS DOUBLE)
    """)

    # Equivalente di str.title() di Python: iniziale maiuscola per ogni parola
    con.execute("""
        CREATE OR REPLACE TEMP MACRO titolo(v) AS
          CASE WHEN v IS NULL THEN NULL ELSE
            array_to_string(
              list_transform(
                string_split(lower(v), ' '),
                p -> CASE WHEN length(p) = 0 THEN p
                          ELSE upper(substr(p, 1, 1)) || substr(p, 2) END
              ), ' ')
          END
    """)

    # Range di dominio: fuori intervallo equivale a dato assente
    con.execute("""
        CREATE OR REPLACE TEMP MACRO entro_range(v, minimo, massimo) AS
          CASE WHEN v IS NULL OR v < minimo OR v > massimo THEN NULL ELSE v END
    """)

    formati = ", ".join(_letterale(f) for f in FORMATI_DATA_SQL)
    con.execute(f"""
        CREATE OR REPLACE TEMP MACRO a_data(v) AS
          try_strptime(pulisci_testo(v), [{formati}])
    """)


def _cte_base(colonne: list[str], percorso_csv: str) -> str:
    """
    Fasi comuni: lettura in streaming, trim, marcatori di nullo e deduplica.

    L'ordine ricalca quello dell'implementazione pandas, comprese le sottigliezze
    che cambiano il risultato: i duplicati si rimuovono DOPO il trim, perché due
    righe identiche a meno di spazi devono contare come una sola.
    """
    elenco = ", ".join(colonne)
    trimmate = ",\n      ".join(f"pulisci_testo({c}) AS {c}" for c in colonne)

    return f"""
    WITH grezzo AS (
      SELECT *, row_number() OVER () AS _ord
      FROM read_csv({_letterale(percorso_csv)}, all_varchar = true, header = true, sample_size = -1)
    ),
    trimmato AS (
      SELECT
      {trimmate},
      _ord
      FROM grezzo
    ),
    senza_duplicati_esatti AS (
      SELECT * FROM trimmato
      QUALIFY row_number() OVER (PARTITION BY {elenco} ORDER BY _ord) = 1
    ),
    senza_duplicati_id AS (
      SELECT * FROM senza_duplicati_esatti
      QUALIFY row_number() OVER (PARTITION BY id_dipendente ORDER BY _ord) = 1
    )"""


def query_fuori_range(colonne: list[str], percorso_csv: str) -> str:
    """Conta, per ogni colonna numerica, i valori leggibili ma fuori dal dominio."""
    conteggi = ",\n      ".join(
        f"count(*) FILTER (a_numero({c}) IS NOT NULL "
        f"AND entro_range(a_numero({c}), {minimo}, {massimo}) IS NULL) AS {c}"
        for c, (minimo, massimo) in RANGE_VALIDI.items()
        if c in colonne
    )
    return f"{_cte_base(colonne, percorso_csv)}\n    SELECT\n      {conteggi}\n    FROM senza_duplicati_id"


def query_pulizia(colonne: list[str], percorso_csv: str) -> str:
    """
    Query completa: dal CSV al dataset normalizzato, senza passare da pandas.

    Le colonne derivate si calcolano PRIMA di azzerare le date di cessazione
    incoerenti, esattamente come nell'implementazione di riferimento.
    """

    # --- fase 3: tipizzazione
    tipizzate = []
    for col in colonne:
        if col == "dipartimento":
            tipizzate.append(f"{_mappa_sql(col, MAPPA_DIPARTIMENTO)} AS {col}")
        elif col == "genere":
            tipizzate.append(f"{_mappa_sql(col, MAPPA_GENERE)} AS {col}")
        elif col == "stato":
            tipizzate.append(
                f"CASE WHEN upper(substr({col}, 1, 1)) || lower(substr({col}, 2)) "
                f"IN ('Attivo', 'Cessato') THEN upper(substr({col}, 1, 1)) || lower(substr({col}, 2)) "
                f"ELSE NULL END AS {col}"
            )
        elif col in COLONNE_TITLE_CASE:
            tipizzate.append(f"titolo({col}) AS {col}")
        elif col in RANGE_VALIDI:
            minimo, massimo = RANGE_VALIDI[col]
            tipizzate.append(f"entro_range(a_numero({col}), {minimo}, {massimo}) AS {col}")
        elif col in COLONNE_DATA:
            tipizzate.append(f"a_data({col}) AS {col}")
        else:
            tipizzate.append(col)
    tipizzate_sql = ",\n      ".join(tipizzate)

    return f"""{_cte_base(colonne, percorso_csv)},
    tipizzato AS (
      SELECT
      {tipizzate_sql},
      _ord
      FROM senza_duplicati_id
    ),
    derivato AS (
      SELECT
        *,
        year(data_assunzione)                                             AS anno_assunzione,
        year(data_cessazione)                                             AS anno_cessazione,
        strftime(data_cessazione, '%Y-%m')                                AS mese_cessazione,
        CAST(CASE WHEN stato = 'Cessato' THEN 1 ELSE 0 END AS TINYINT)    AS is_cessato,
        round(date_diff('day', data_assunzione, data_cessazione) / 365.25, 2) AS durata_rapporto_anni
      FROM tipizzato
    )
    SELECT
      * EXCLUDE (_ord, data_cessazione),
      -- coerenza: un dipendente in forza non può avere una data di cessazione.
      -- Si azzera DOPO le colonne derivate, come nell'implementazione pandas.
      CASE WHEN stato = 'Attivo' THEN NULL ELSE data_cessazione END AS data_cessazione
    FROM derivato
    ORDER BY _ord
    """


def colonne_sorgente(con: duckdb.DuckDBPyConnection, percorso_csv: str) -> list[str]:
    """Nomi delle colonne del CSV, senza leggerne il contenuto."""
    righe = con.execute(
        f"DESCRIBE SELECT * FROM read_csv({_letterale(percorso_csv)}, all_varchar = true, header = true)"
    ).fetchall()
    return [r[0] for r in righe]
