from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request
from flask_cors import CORS
import mysql.connector
from mysql.connector import Error as MySQLError

# Dialogflow è opzionale: se configurato viene usato come motore NLU principale.
# Se non è configurato, il progetto continua a funzionare con il riconoscimento locale.
try:
    from google.cloud import dialogflow_v2 as dialogflow
except ImportError:
    dialogflow = None


app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    "host": os.getenv("SMART_PANTRY_DB_HOST", "localhost"),
    "user": os.getenv("SMART_PANTRY_DB_USER", "smart_user"),
    "password": os.getenv("SMART_PANTRY_DB_PASSWORD", "smartpass"),
    "database": os.getenv("SMART_PANTRY_DB_NAME", "smart_pantry"),
}

DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID", "").strip()
DIALOGFLOW_LANGUAGE_CODE = os.getenv("DIALOGFLOW_LANGUAGE_CODE", "it-IT")
DIALOGFLOW_ENABLED = bool(dialogflow is not None and DIALOGFLOW_PROJECT_ID)

SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_HISTORY_ITEMS = 30
SESSIONI: dict[str, dict[str, Any]] = {}

ALIMENTI = [
    "banana",
    "apple",
    "orange",
    "broccoli",
    "carrot",
    "pizza",
    "sandwich",
    "hot dog",
    "donut",
    "cake",
    "latte",
    "uova",
    "pane",
    "yogurt",
    "cracker",
]

NOMI_ALIMENTI = {
    "banana": "banana",
    "apple": "mela",
    "orange": "arancia",
    "broccoli": "broccoli",
    "carrot": "carota",
    "pizza": "pizza",
    "sandwich": "sandwich",
    "hot dog": "hot dog",
    "donut": "donut",
    "cake": "torta",
    "latte": "latte",
    "uova": "uova",
    "pane": "pane",
    "yogurt": "yogurt",
    "cracker": "cracker",
}

INTENT_ALIASES = {
    "richiedi_alternative": {
        "richiedi alternative",
        "richiedi alternativa",
        "alternativa",
        "alternative",
    },
    "altra_alternativa": {
        "altra alternativa",
        "altre alternative",
        "dammene un altra",
        "dammene un'altra",
    },
    "lista_alternative": {
        "lista alternative",
        "alternative sicure",
        "mostra alternative",
    },
    "controlla_compatibilita": {
        "controlla compatibilita",
        "compatibilita",
        "posso mangiarlo",
    },
    "chiedi_allergeni": {
        "chiedi allergeni",
        "allergeni",
        "ingredienti allergenici",
    },
    "info_progetto": {
        "info progetto",
        "spiega progetto",
        "funzionamento progetto",
    },
    "info_modelli": {
        "info modelli",
        "modelli visivi",
        "teachable machine",
        "coco ssd",
        "blazeface",
    },
    "info_database": {
        "info database",
        "database",
        "mysql",
        "flask",
    },
    "info_profilo": {
        "info profilo",
        "profilo utente",
        "utente riconosciuto",
    },
    "limiti_privacy": {
        "limiti privacy",
        "privacy",
        "limiti",
        "affidabilita",
    },
    "ripeti_risposta": {
        "ripeti risposta",
        "ripeti",
        "non ho sentito",
    },
    "semplifica_risposta": {
        "semplifica risposta",
        "spiega semplice",
    },
    "riassumi_risposta": {
        "riassumi risposta",
        "riassumi",
    },
    "saluti": {
        "saluti",
        "ciao",
        "grazie",
    },
}


def nuova_sessione() -> dict[str, Any]:
    return {
        "utente": "",
        "alimento": "",
        "indice_alternativa": 0,
        "ultimo_utente_alternativa": "",
        "ultimo_alimento_alternativa": "",
        "ultimo_messaggio_utente": "",
        "ultima_risposta": "",
        "history": [],
        "updated_at": time.time(),
    }


def pulisci_sessioni_scadute() -> None:
    adesso = time.time()
    scadute = [
        session_id
        for session_id, sessione in SESSIONI.items()
        if adesso - sessione.get("updated_at", adesso) > SESSION_TTL_SECONDS
    ]

    for session_id in scadute:
        SESSIONI.pop(session_id, None)


def normalizza_session_id(session_id: str | None) -> str:
    session_id = (session_id or "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", session_id):
        return uuid.uuid4().hex

    return session_id


def prendi_sessione(session_id: str) -> dict[str, Any]:
    pulisci_sessioni_scadute()

    if session_id not in SESSIONI:
        SESSIONI[session_id] = nuova_sessione()

    SESSIONI[session_id]["updated_at"] = time.time()
    return SESSIONI[session_id]


def aggiungi_history(sessione: dict[str, Any], ruolo: str, testo: str) -> None:
    history = sessione.setdefault("history", [])
    history.append({"role": ruolo, "text": testo})

    if len(history) > MAX_HISTORY_ITEMS:
        del history[:-MAX_HISTORY_ITEMS]


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def database_disponibile() -> tuple[bool, str]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return True, ""
    except MySQLError as error:
        return False, str(error)


def nome_alimento(alimento: str | None) -> str:
    if not alimento:
        return ""

    return NOMI_ALIMENTI.get(alimento, alimento)


def normalizza_testo(testo: Any) -> str:
    if testo is None:
        return ""

    testo = str(testo).lower().strip()
    sostituzioni = {
        "’": "'",
        "‘": "'",
        "`": "'",
        "à": "a",
        "è": "e",
        "é": "e",
        "ì": "i",
        "ò": "o",
        "ù": "u",
    }

    for origine, destinazione in sostituzioni.items():
        testo = testo.replace(origine, destinazione)

    testo = re.sub(r"\s+", " ", testo)
    testo = testo.replace("torta", "cake")
    testo = re.sub(r"\buovo\b", "uova", testo)

    return testo


def trova_utente(testo: str) -> str:
    testo_norm = normalizza_testo(testo)

    for nome in ("Pasquale", "Carmine", "Francesco"):
        if nome.lower() in testo_norm:
            return nome

    return ""


def trova_alimento(testo: str) -> str:
    testo_norm = normalizza_testo(testo)

    alias = {
        "mela": "apple",
        "arancia": "orange",
        "carota": "carrot",
        "torta": "cake",
    }

    for parola, alimento in alias.items():
        if parola in testo_norm:
            return alimento

    for alimento in sorted(ALIMENTI, key=len, reverse=True):
        if alimento in testo_norm:
            return alimento

    return ""


def prendi_utente(nome: str) -> dict[str, Any] | None:
    if not nome:
        return None

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT * FROM utenti WHERE LOWER(nome) = LOWER(%s)",
            (nome,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def prendi_prodotto(nome: str) -> dict[str, Any] | None:
    if not nome:
        return None

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT * FROM prodotti WHERE LOWER(nome) = LOWER(%s)",
            (nome,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def testo_in_lista(testo: Any) -> list[str]:
    if testo is None or str(testo).strip() == "":
        return []

    return [
        elemento.strip().lower()
        for elemento in str(testo).split(",")
        if elemento.strip()
    ]


def controlla_rischio(
    utente: dict[str, Any],
    prodotto: dict[str, Any],
) -> list[str]:
    allergia_utente = testo_in_lista(utente.get("allergia"))
    intolleranza_utente = testo_in_lista(utente.get("intolleranza"))
    allergeni_prodotto = testo_in_lista(prodotto.get("allergene"))
    profilo_utente = allergia_utente + intolleranza_utente

    rischi: list[str] = []

    for elemento in profilo_utente:
        for allergene in allergeni_prodotto:
            if elemento in allergene or allergene in elemento:
                rischi.append(elemento)

    return sorted(set(rischi))


def prendi_alternative(prodotto: dict[str, Any]) -> list[str]:
    # Supporta sia "alternativa" sia "alternativa1".
    possibili_colonne = [
        "alternativa",
        "alternativa1",
        "alternativa2",
        "alternativa3",
    ]

    alternative: list[str] = []

    for colonna in possibili_colonne:
        valore = prodotto.get(colonna)

        if valore is not None and str(valore).strip():
            valore_testo = str(valore).strip()

            if valore_testo not in alternative:
                alternative.append(valore_testo)

    return alternative


def risolvi_contesto(
    sessione: dict[str, Any],
    utente_nome: str = "",
    alimento: str = "",
) -> tuple[str, str]:
    utente_nome = utente_nome or sessione.get("utente", "")
    alimento = alimento or sessione.get("alimento", "")
    return utente_nome, alimento


def aggiorna_contesto_da_richiesta(
    sessione: dict[str, Any],
    testo: str,
    user_name: str,
    food_name: str,
) -> None:
    utente = user_name.strip() or trova_utente(testo)
    alimento = normalizza_testo(food_name) or trova_alimento(testo)

    if utente:
        sessione["utente"] = utente

    if alimento:
        sessione["alimento"] = alimento


def risposta_compatibilita(
    sessione: dict[str, Any],
    utente_nome: str = "",
    alimento: str = "",
) -> str:
    utente_nome, alimento = risolvi_contesto(sessione, utente_nome, alimento)

    if not utente_nome:
        return "Prima riconosci l'utente, così posso usare il profilo corretto."

    if not alimento:
        return "Prima seleziona un alimento con la webcam oppure scrivimi il suo nome."

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database, quindi non posso "
            "verificarne la compatibilità."
        )

    allergene_prodotto = prodotto.get("allergene")
    rischi = controlla_rischio(utente, prodotto)

    if not allergene_prodotto or not str(allergene_prodotto).strip():
        return (
            f"Sì, {utente['nome']}: {nome_alimento(alimento)} non ha allergeni "
            "principali registrati nel database."
        )

    if not rischi:
        return (
            f"Sì, {utente['nome']}: {nome_alimento(alimento)} è compatibile con "
            f"il tuo profilo. Può contenere {allergene_prodotto}, ma questi elementi "
            "non risultano tra le tue allergie o intolleranze."
        )

    return (
        f"No, {utente['nome']}: {nome_alimento(alimento)} non è compatibile con "
        f"il tuo profilo. Può contenere {allergene_prodotto}; nel profilo risulta "
        f"incompatibilità con {', '.join(rischi)}."
    )


def risposta_alternativa(
    sessione: dict[str, Any],
    continua: bool = False,
) -> str:
    utente_nome, alimento = risolvi_contesto(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente, così posso personalizzare l'alternativa."

    if not alimento:
        return (
            "Prima seleziona un alimento con la webcam. Poi posso suggerire "
            "un'alternativa adatta al profilo."
        )

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. Aggiungilo alla "
            "tabella prodotti per gestire allergeni e alternative."
        )

    allergene_prodotto = prodotto.get("allergene")
    alternative = prendi_alternative(prodotto)
    rischi = controlla_rischio(utente, prodotto)

    if not allergene_prodotto or not str(allergene_prodotto).strip():
        return (
            f"{utente['nome']}, {nome_alimento(alimento)} non ha allergeni "
            "principali registrati: non serve un'alternativa specifica."
        )

    if not rischi:
        return (
            f"{utente['nome']}, {nome_alimento(alimento)} non risulta incompatibile "
            "con il tuo profilo. Puoi comunque controllare l'etichetta reale."
        )

    if not alternative:
        return (
            f"{utente['nome']}, {nome_alimento(alimento)} può contenere "
            f"{allergene_prodotto}, ma nel database non sono presenti alternative."
        )

    stessa_richiesta = (
        sessione.get("ultimo_utente_alternativa") == utente_nome
        and sessione.get("ultimo_alimento_alternativa") == alimento
    )

    if not stessa_richiesta:
        sessione["ultimo_utente_alternativa"] = utente_nome
        sessione["ultimo_alimento_alternativa"] = alimento
        sessione["indice_alternativa"] = 0
    elif continua:
        sessione["indice_alternativa"] = sessione.get("indice_alternativa", 0) + 1
    else:
        sessione["indice_alternativa"] = 0

    indice = sessione.get("indice_alternativa", 0)

    if indice >= len(alternative):
        sessione["indice_alternativa"] = len(alternative) - 1
        return (
            f"Non ho altre alternative registrate per {nome_alimento(alimento)}. "
            f"Quelle disponibili sono: {', '.join(alternative)}."
        )

    alternativa = alternative[indice]
    rischio_testo = ", ".join(rischi)

    if indice == 0:
        return (
            f"{utente['nome']}, per {nome_alimento(alimento)} ho rilevato un rischio "
            f"legato a {rischio_testo}. L'alternativa consigliata è {alternativa}."
        )

    return (
        f"Un'altra alternativa per {nome_alimento(alimento)} è {alternativa}. "
        "È una possibile opzione da valutare al posto del prodotto originale."
    )


def risposta_alternative_sicure(sessione: dict[str, Any]) -> str:
    utente_nome, alimento = risolvi_contesto(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente per vedere alternative personalizzate."

    if not alimento:
        return "Prima seleziona un alimento con la webcam."

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    alternative = prendi_alternative(prodotto)

    if not alternative:
        return f"Per {nome_alimento(alimento)} non ho alternative registrate."

    rischi = controlla_rischio(utente, prodotto)
    elenco = "; ".join(alternative)

    if rischi:
        return (
            f"Per {utente['nome']}, {nome_alimento(alimento)} presenta un rischio "
            f"legato a {', '.join(rischi)}. Le alternative disponibili sono: {elenco}."
        )

    return (
        f"{nome_alimento(alimento)} è compatibile con il profilo di {utente['nome']}. "
        f"Nel database sono comunque presenti queste alternative: {elenco}."
    )


def risposta_allergeni(
    sessione: dict[str, Any],
    testo: str,
) -> str:
    utente_nome, alimento = risolvi_contesto(
        sessione,
        trova_utente(testo),
        trova_alimento(testo),
    )

    if not alimento:
        return (
            "Dimmi l'alimento di cui vuoi conoscere gli allergeni, oppure "
            "selezionalo con la webcam."
        )

    prodotto = prendi_prodotto(alimento)

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    allergene = prodotto.get("allergene")

    if not allergene or not str(allergene).strip():
        return (
            f"{nome_alimento(alimento)} non ha allergeni principali registrati "
            "nel database."
        )

    if not utente_nome:
        return (
            f"Gli allergeni registrati per {nome_alimento(alimento)} sono: "
            f"{allergene}. Riconosci un utente per il controllo personalizzato."
        )

    utente = prendi_utente(utente_nome)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    rischi = controlla_rischio(utente, prodotto)

    if rischi:
        return (
            f"Gli allergeni registrati per {nome_alimento(alimento)} sono: "
            f"{allergene}. Per {utente['nome']} è rilevante l'incompatibilità "
            f"con {', '.join(rischi)}."
        )

    return (
        f"Gli allergeni registrati per {nome_alimento(alimento)} sono: "
        f"{allergene}. Per {utente['nome']} non risultano incompatibilità dirette."
    )


def risposta_allergene_specifico(
    sessione: dict[str, Any],
    allergene_richiesto: str,
) -> str:
    _, alimento = risolvi_contesto(sessione)

    if not alimento:
        return "Prima seleziona l'alimento da controllare."

    prodotto = prendi_prodotto(alimento)

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    allergeni = testo_in_lista(prodotto.get("allergene"))
    presente = any(
        allergene_richiesto in voce or voce in allergene_richiesto
        for voce in allergeni
    )

    if presente:
        return (
            f"Sì: per {nome_alimento(alimento)} il database segnala "
            f"{allergene_richiesto}. Controlla comunque l'etichetta reale."
        )

    return (
        f"Nel database {nome_alimento(alimento)} non risulta associato a "
        f"{allergene_richiesto}. Controlla comunque l'etichetta reale."
    )


def risposta_utente(sessione: dict[str, Any], testo: str) -> str:
    utente_nome, _ = risolvi_contesto(sessione)

    if not utente_nome:
        return "Al momento non è stato riconosciuto alcun utente."

    utente = prendi_utente(utente_nome)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    testo_norm = normalizza_testo(testo)
    allergia = utente.get("allergia") or "nessuna"
    intolleranza = utente.get("intolleranza") or "nessuna"

    if "eta" in testo_norm or "anni" in testo_norm:
        return f"Nel profilo di {utente['nome']} risultano {utente['eta']} anni."

    if "quale utente" in testo_norm or "chi sono" in testo_norm or "mi riconosci" in testo_norm:
        return f"L'utente riconosciuto è {utente['nome']}."

    if "allerg" in testo_norm or "intoller" in testo_norm or "incompatibil" in testo_norm:
        return (
            f"Nel profilo di {utente['nome']}: allergia {allergia}; "
            f"intolleranza {intolleranza}."
        )

    return (
        f"Profilo attivo: {utente['nome']}, {utente['eta']} anni. "
        f"Allergia: {allergia}. Intolleranza: {intolleranza}."
    )


def risposta_alimento_corrente(sessione: dict[str, Any]) -> str:
    alimento = sessione.get("alimento", "")

    if not alimento:
        return "Al momento non è selezionato alcun alimento."

    return f"L'alimento selezionato è {nome_alimento(alimento)}."


def risposta_progetto(testo: str = "") -> str:
    testo_norm = normalizza_testo(testo)

    if (
        "sviluppi futuri" in testo_norm
        or "miglioramenti futuri" in testo_norm
        or "si potrebbero aggiungere" in testo_norm
    ):
        return (
            "Tra gli sviluppi futuri si potrebbero aggiungere più alimenti, profili "
            "modificabili, lettura automatica delle etichette e un database più ampio."
        )

    return (
        "Smart Pantry Tutor riconosce l'utente e l'alimento, consulta MySQL "
        "e fornisce controlli e alternative personalizzati."
    )


def risposta_funzionamento() -> str:
    return (
        "Il flusso è: riconoscimento utente, riconoscimento alimento, controllo "
        "del profilo nel database e risposta personalizzata tramite assistente."
    )


def risposta_moduli() -> str:
    return (
        "I moduli principali sono quattro: riconoscimento utente, riconoscimento "
        "alimento, database MySQL e assistente conversazionale con chat e voce."
    )


def risposta_modelli(testo: str) -> str:
    testo_norm = normalizza_testo(testo)

    if "blazeface" in testo_norm or "volto" in testo_norm:
        return (
            "BlazeFace individua il volto nella webcam. Il ritaglio viene poi "
            "classificato dal modello Teachable Machine degli utenti."
        )

    if "coco" in testo_norm:
        return (
            "COCO-SSD rileva alimenti già presenti nel dataset COCO, come pizza, "
            "banana, hot dog e torta."
        )

    if "teachable" in testo_norm:
        return (
            "Teachable Machine classifica i volti e gli alimenti personalizzati "
            "come latte, uova, pane e yogurt."
        )

    if "differenza" in testo_norm and (
        "rilevamento" in testo_norm or "classificazione" in testo_norm
    ):
        return (
            "Il rilevamento trova la posizione dell'oggetto; la classificazione "
            "decide a quale classe appartiene il ritaglio analizzato."
        )

    if "rilevamenti" in testo_norm or "conferme consecutive" in testo_norm:
        return (
            "Il sistema richiede più rilevamenti consecutivi per evitare di bloccare "
            "un risultato dovuto a un singolo fotogramma incerto o a un errore momentaneo."
        )

    if "browser" in testo_norm:
        return (
            "Sì. I modelli visivi vengono eseguiti nel browser tramite TensorFlow.js; "
            "il backend Flask viene contattato per la chat e per interrogare MySQL."
        )

    return (
        "Smart Pantry usa BlazeFace per localizzare il volto, Teachable Machine "
        "per le classi personalizzate e COCO-SSD per diversi alimenti comuni."
    )


def risposta_database(testo: str) -> str:
    testo_norm = normalizza_testo(testo)

    if "flask" in testo_norm:
        return (
            "Flask riceve le richieste dal sito, interroga MySQL e restituisce "
            "la risposta personalizzata in formato JSON."
        )

    if "frontend" in testo_norm or "backend" in testo_norm or "comunica" in testo_norm:
        return (
            "Il frontend invia una richiesta HTTP al backend Flask sulla porta "
            "5000. Flask consulta MySQL e restituisce la risposta."
        )

    if "alternative" in testo_norm and ("dove" in testo_norm or "arriv" in testo_norm):
        return "Le alternative sono lette dalle colonne dedicate nella tabella prodotti."

    if "non disponibile" in testo_norm:
        return (
            "Se MySQL non è disponibile, il controllo personalizzato non può essere "
            "eseguito; la parte visiva può comunque continuare a funzionare."
        )

    return (
        "MySQL contiene profili utente, allergie, intolleranze, prodotti, allergeni "
        "e alternative. Flask usa questi dati per personalizzare la risposta."
    )


def risposta_privacy_limiti(testo: str) -> str:
    testo_norm = normalizza_testo(testo)

    if "salv" in testo_norm and ("immagin" in testo_norm or "foto" in testo_norm):
        return (
            "Durante l'uso normale, le immagini della webcam vengono elaborate nel "
            "browser e non sono salvate dal backend."
        )

    if "etichetta" in testo_norm:
        return (
            "No. Smart Pantry non sostituisce il controllo dell'etichetta reale: "
            "il riconoscimento può sbagliare e il database contiene informazioni "
            "dimostrative."
        )

    if "privacy" in testo_norm or "proteg" in testo_norm:
        return (
            "Ogni browser usa una sessione conversazionale separata. I messaggi sono "
            "mantenuti temporaneamente in memoria e non vengono scritti nel database."
        )

    if "affidabil" in testo_norm or "sbaglia" in testo_norm:
        return (
            "Il riconoscimento usa soglie e conferme consecutive, ma non è infallibile. "
            "Luce, inquadratura e qualità del dataset possono influire."
        )

    return (
        "I limiti principali sono il numero di alimenti conosciuti, la qualità del "
        "dataset e la necessità di verificare sempre l'etichetta reale."
    )


def risposta_semplice(ultima_risposta: str) -> str:
    if not ultima_risposta:
        return "Non ho ancora una risposta precedente da semplificare."

    frasi = re.split(r"(?<=[.!?])\s+", ultima_risposta.strip())
    breve = " ".join(frasi[:2]).strip()
    return breve or ultima_risposta


def risposta_riassunta(ultima_risposta: str) -> str:
    if not ultima_risposta:
        return "Non ho ancora una risposta precedente da riassumere."

    prima_frase = re.split(r"(?<=[.!?])\s+", ultima_risposta.strip())[0]
    return prima_frase.strip()


def classifica_intento_locale(testo: str) -> tuple[str, float]:
    t = normalizza_testo(testo)

    if not t:
        return "fallback", 0.0

    if any(frase in t for frase in ("ripeti la risposta", "puoi ripetere", "non ho sentito", "ripeti")):
        return "ripeti_risposta", 0.96

    if any(frase in t for frase in ("piu semplice", "spiegalo semplice", "semplifica")):
        return "semplifica_risposta", 0.94

    if any(frase in t for frase in ("riassumi", "in una frase", "brevemente")):
        return "riassumi_risposta", 0.94

    if any(frase in t for frase in ("grazie", "ti ringrazio")):
        return "ringraziamento", 0.98

    if any(frase in t for frase in ("ciao", "buongiorno", "buonasera", "alla prossima", "arrivederci", "a presto")):
        return "saluti", 0.97

    if any(frase in t for frase in (
        "tutte le alternative",
        "alternative sicure",
        "quali alternative",
        "elenco alternative",
    )):
        return "lista_alternative", 0.96

    if any(frase in t for frase in (
        "dammene un'altra",
        "dammene un altra",
        "un'altra alternativa",
        "un altra alternativa",
        "qualcos'altro",
        "non mi piace",
        "opzione diversa",
    )):
        return "altra_alternativa", 0.96

    if any(frase in t for frase in (
        "alternativa",
        "alternative",
        "richiedi alternative",
        "dammi un alternativa",
        "dammi un'alternativa",
        "voglio delle alternative",
        "mostrami alternative",
        "al posto",
        "cosa posso mangiare",
        "consigliami",
        "suggeriscimi",
        "prodotto simile",
    )):
        return "richiedi_alternative", 0.93

    if any(frase in t for frase in (
        "posso mangiare",
        "compatibile",
        "sicuro per me",
        "va bene per me",
        "incompatibil",
        "mi fa male",
    )):
        return "controlla_compatibilita", 0.95

    if "contiene glutine" in t:
        return "contiene_glutine", 0.98

    if "contiene lattosio" in t:
        return "contiene_lattosio", 0.98

    if "contiene uova" in t:
        return "contiene_uova", 0.98

    if any(frase in t for frase in ("allergen", "cosa contiene", "che contiene", "ingredienti", "tracce")):
        return "chiedi_allergeni", 0.94

    if any(frase in t for frase in (
        "che alimento e selezionato",
        "alimento selezionato",
        "prodotto selezionato",
    )):
        return "alimento_corrente", 0.97

    if any(frase in t for frase in (
        "quale utente",
        "chi sono",
        "mi riconosci",
        "profilo",
        "eta",
        "allergie",
        "intolleranze",
        "dati del profilo",
    )):
        return "info_profilo", 0.92

    if any(frase in t for frase in (
        "teachable",
        "coco",
        "blazeface",
        "modello",
        "riconosci il volto",
        "riconosci il cibo",
        "rilevamento",
        "rilevamenti",
        "piu rilevamenti",
        "conferme consecutive",
        "classificazione",
        "nel browser",
        "avviene nel browser",
        "elaborazione nel browser",
    )):
        return "info_modelli", 0.91

    if any(frase in t for frase in (
        "database",
        "mysql",
        "flask",
        "frontend",
        "backend",
        "origine alternative",
        "da dove arrivano le alternative",
        "dove arrivano le alternative",
        "alternative suggerite",
    )):
        return "info_database", 0.93

    if any(frase in t for frase in (
        "privacy",
        "salvate le immagini",
        "salvi le immagini",
        "immagini salvate",
        "immagini vengono salvate",
        "le immagini vengono salvate",
        "affidabile",
        "puo sbagliare",
        "limiti",
        "sostituisce l'etichetta",
        "sostituisce il controllo dell'etichetta",
        "controllo dell'etichetta",
    )):
        return "limiti_privacy", 0.92

    if any(frase in t for frase in ("moduli", "componenti del progetto")):
        return "moduli", 0.94

    if any(frase in t for frase in ("come funziona", "funzionamento", "flusso completo")):
        return "funzionamento", 0.93

    if any(frase in t for frase in (
        "spiegami il progetto",
        "progetto in breve",
        "obiettivo",
        "cosa fa smart pantry",
        "smart pantry",
        "sviluppi futuri",
        "miglioramenti futuri",
        "miglioramenti si potrebbero aggiungere",
        "cosa si potrebbe aggiungere",
    )):
        return "info_progetto", 0.90

    if "come stai" in t:
        return "conversazione", 0.90

    return "fallback", 0.0


def normalizza_nome_intent(nome: str) -> str:
    nome = normalizza_testo(nome)
    nome = re.sub(r"[^a-z0-9 ]+", " ", nome)
    return re.sub(r"\s+", " ", nome).strip()


def canonicalizza_intent_dialogflow(nome_intent: str) -> str:
    nome_norm = normalizza_nome_intent(nome_intent)

    for canonicale, alias_set in INTENT_ALIASES.items():
        if nome_norm == normalizza_nome_intent(canonicale):
            return canonicale

        for alias in alias_set:
            alias_norm = normalizza_nome_intent(alias)

            if nome_norm == alias_norm or alias_norm in nome_norm:
                return canonicale

    return ""


def rileva_intent_dialogflow(
    testo: str,
    session_id: str,
) -> dict[str, Any] | None:
    if not DIALOGFLOW_ENABLED:
        return None

    try:
        sessions_client = dialogflow.SessionsClient()
        session_path = sessions_client.session_path(
            DIALOGFLOW_PROJECT_ID,
            session_id,
        )

        text_input = dialogflow.TextInput(
            text=testo,
            language_code=DIALOGFLOW_LANGUAGE_CODE,
        )
        query_input = dialogflow.QueryInput(text=text_input)

        response = sessions_client.detect_intent(
            request={
                "session": session_path,
                "query_input": query_input,
            }
        )

        query_result = response.query_result
        intent = query_result.intent
        display_name = intent.display_name if intent else ""
        is_fallback = bool(getattr(intent, "is_fallback", False)) if intent else True

        return {
            "display_name": display_name,
            "canonical_intent": canonicalizza_intent_dialogflow(display_name),
            "confidence": float(query_result.intent_detection_confidence or 0.0),
            "fulfillment_text": query_result.fulfillment_text or "",
            "is_fallback": is_fallback,
        }
    except Exception as error:
        # Il sistema resta operativo anche se Dialogflow è momentaneamente non raggiungibile.
        app.logger.warning("Dialogflow non disponibile: %s", error)
        return None


def suggerimenti_contestuali(sessione: dict[str, Any]) -> list[str]:
    utente = sessione.get("utente", "")
    alimento = sessione.get("alimento", "")

    if utente and alimento:
        return [
            "Posso mangiarlo?",
            "Che allergeni contiene?",
            "Dammi un'alternativa",
            "Spiegamelo più semplicemente",
        ]

    if utente:
        return [
            "Quali dati contiene il mio profilo?",
            "Quali sono le mie incompatibilità?",
            "Come funziona il sistema?",
        ]

    return [
        "Come funziona Smart Pantry?",
        "Quali sono i moduli del progetto?",
        "Che ruolo ha il database?",
    ]


def esegui_intento(
    intent: str,
    testo: str,
    sessione: dict[str, Any],
) -> tuple[str, bool]:
    if intent == "ripeti_risposta":
        ultima = sessione.get("ultima_risposta", "")
        return (
            ultima or "Non ho ancora una risposta precedente da ripetere.",
            bool(ultima),
        )

    if intent == "semplifica_risposta":
        return risposta_semplice(sessione.get("ultima_risposta", "")), True

    if intent == "riassumi_risposta":
        return risposta_riassunta(sessione.get("ultima_risposta", "")), True

    if intent == "ringraziamento":
        return "Prego, sono qui per aiutarti.", True

    if intent == "saluti":
        testo_norm = normalizza_testo(testo)

        if any(frase in testo_norm for frase in ("arrivederci", "alla prossima", "a presto")):
            return "Ciao, alla prossima.", True

        return "Ciao! Puoi chiedermi informazioni sul progetto o sul prodotto selezionato.", True

    if intent == "conversazione":
        return "Sto bene e sono pronto ad aiutarti con Smart Pantry.", True

    if intent == "lista_alternative":
        return risposta_alternative_sicure(sessione), True

    if intent == "altra_alternativa":
        return risposta_alternativa(sessione, continua=True), True

    if intent == "richiedi_alternative":
        return risposta_alternativa(sessione, continua=False), True

    if intent == "controlla_compatibilita":
        return risposta_compatibilita(sessione), True

    if intent == "contiene_glutine":
        return risposta_allergene_specifico(sessione, "glutine"), True

    if intent == "contiene_lattosio":
        return risposta_allergene_specifico(sessione, "lattosio"), True

    if intent == "contiene_uova":
        return risposta_allergene_specifico(sessione, "uova"), True

    if intent == "chiedi_allergeni":
        return risposta_allergeni(sessione, testo), True

    if intent == "info_profilo":
        return risposta_utente(sessione, testo), True

    if intent == "alimento_corrente":
        return risposta_alimento_corrente(sessione), True

    if intent == "info_modelli":
        return risposta_modelli(testo), True

    if intent == "info_database":
        return risposta_database(testo), True

    if intent == "limiti_privacy":
        return risposta_privacy_limiti(testo), True

    if intent == "moduli":
        return risposta_moduli(), True

    if intent == "funzionamento":
        return risposta_funzionamento(), True

    if intent == "info_progetto":
        return risposta_progetto(testo), True

    return (
        "Non sono sicuro di aver capito. Puoi ripetere o riformulare la domanda? "
        "Posso aiutarti con profilo, alimento, allergeni, compatibilità, alternative "
        "e funzionamento del progetto.",
        False,
    )


@app.route("/", methods=["GET"])
def home():
    return "Backend Smart Pantry attivo."


@app.route("/health", methods=["GET"])
def health():
    db_ok, db_error = database_disponibile()

    return jsonify(
        {
            "backend": True,
            "database": db_ok,
            "database_error": "" if db_ok else db_error,
            "dialogflow": DIALOGFLOW_ENABLED,
            "dialogflow_project": DIALOGFLOW_PROJECT_ID if DIALOGFLOW_ENABLED else "",
        }
    )


@app.route("/reset-session", methods=["POST"])
def reset_session():
    data = request.get_json(silent=True) or {}
    session_id = normalizza_session_id(data.get("session_id"))

    SESSIONI.pop(session_id, None)

    return jsonify(
        {
            "ok": True,
            "session_id": session_id,
        }
    )


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    user_message = str(data.get("message", "")).strip()
    user_name = str(data.get("user", "")).strip()
    food_name = str(data.get("food", "")).strip()
    session_id = normalizza_session_id(data.get("session_id"))

    sessione = prendi_sessione(session_id)
    aggiorna_contesto_da_richiesta(
        sessione,
        user_message,
        user_name,
        food_name,
    )

    if not user_message:
        return jsonify(
            {
                "reply": "Scrivi o pronuncia una domanda.",
                "understood": False,
                "intent": "fallback",
                "confidence": 0.0,
                "suggestions": suggerimenti_contestuali(sessione),
                "session_id": session_id,
                "source": "locale",
            }
        ), 400

    aggiungi_history(sessione, "user", user_message)

    dialogflow_result = rileva_intent_dialogflow(user_message, session_id)
    source = "locale"
    intent = ""
    confidence = 0.0
    fulfillment_text = ""

    if dialogflow_result and not dialogflow_result["is_fallback"]:
        intent = dialogflow_result["canonical_intent"]
        confidence = dialogflow_result["confidence"]
        fulfillment_text = dialogflow_result["fulfillment_text"]
        source = "dialogflow"

    if not intent:
        intent, confidence = classifica_intento_locale(user_message)

    risposta, understood = esegui_intento(
        intent,
        user_message,
        sessione,
    )

    # Se Dialogflow ha riconosciuto un intent non mappato ma ha una risposta valida,
    # usiamo il fulfillment invece del fallback locale.
    if (
        not understood
        and dialogflow_result
        and not dialogflow_result["is_fallback"]
        and fulfillment_text.strip()
    ):
        risposta = fulfillment_text.strip()
        understood = True
        intent = dialogflow_result["display_name"] or "dialogflow"
        confidence = dialogflow_result["confidence"]
        source = "dialogflow"

    sessione["ultimo_messaggio_utente"] = user_message

    if intent != "ripeti_risposta":
        sessione["ultima_risposta"] = risposta

    aggiungi_history(sessione, "assistant", risposta)
    sessione["updated_at"] = time.time()

    return jsonify(
        {
            "reply": risposta,
            "understood": understood,
            "intent": intent,
            "confidence": round(float(confidence), 3),
            "suggestions": [] if understood else suggerimenti_contestuali(sessione),
            "session_id": session_id,
            "source": source,
            "dialogflow_enabled": DIALOGFLOW_ENABLED,
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
