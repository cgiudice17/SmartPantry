from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from difflib import get_close_matches
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

# Sentence Transformers è opzionale.
# Se installato, viene usato soltanto quando regole e Dialogflow non comprendono la frase.
try:
    from sentence_transformers import SentenceTransformer, util
except ImportError:
    SentenceTransformer = None
    util = None

# OpenAI e HTTPX sono opzionali. Il backend continua a funzionare
# con Dialogflow/regole locali anche quando la chiave non è configurata.
try:
    import httpx
    from openai import BadRequestError, OpenAI
except ImportError:
    httpx = None
    BadRequestError = Exception
    OpenAI = None


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

SEMANTIC_MODEL_NAME = os.getenv(
    "SMART_PANTRY_SEMANTIC_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
).strip()
SEMANTIC_THRESHOLD = float(
    os.getenv("SMART_PANTRY_SEMANTIC_THRESHOLD", "0.56")
)
SEMANTIC_MARGIN = float(
    os.getenv("SMART_PANTRY_SEMANTIC_MARGIN", "0.05")
)
SEMANTIC_AVAILABLE = bool(
    SentenceTransformer is not None and util is not None
)

MODELLO_SEMANTICO = None
EMBEDDING_ESEMPI = None
ETICHETTE_ESEMPI: list[str] = []
LOCK_MODELLO_SEMANTICO = threading.Lock()

OPENAI_MODEL = os.getenv("SMART_PANTRY_OPENAI_MODEL", "gpt-5-mini").strip()
OPENAI_API_KEY_PRESENT = bool(os.getenv("OPENAI_API_KEY", "").strip())
OPENAI_AVAILABLE = bool(
    OpenAI is not None
    and httpx is not None
    and OPENAI_API_KEY_PRESENT
)
OPENAI_CLIENT = None
OPENAI_HTTP_CLIENT = None
LOCK_OPENAI_CLIENT = threading.Lock()
OPENAI_MAX_HISTORY_ITEMS = 10

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
    "spiega_compatibilita": {
        "spiega compatibilita",
        "motivo compatibilita",
        "spiegami il motivo",
    },
    "dati_controllo": {
        "dati controllo",
        "quali dati hai confrontato",
        "dati del profilo confrontati",
    },
    "spiega_alternativa": {
        "spiega alternativa",
        "perche questa alternativa",
        "motivo alternativa",
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

# I pulsanti dell'interfaccia continuano a usare le funzioni Python
# deterministiche. Le domande scritte liberamente vengono invece affidate
# a OpenAI, che riceve i dati reali letti da MySQL.
COMANDI_RAPIDI_ESATTI: dict[str, str] = {
    # Alternative
    "richiedi alternative": "richiedi_alternative",
    "dammi un alternativa": "richiedi_alternative",
    "dammene un altra": "altra_alternativa",
    "dammi un altra alternativa": "altra_alternativa",
    "mostra tutte le alternative": "lista_alternative",
    "mostrami tutte le alternative sicure": "lista_alternative",
    "perche questa alternativa": "spiega_alternativa",
    "perche questa alternativa e adatta a me": "spiega_alternativa",

    # Compatibilità
    "posso mangiarlo": "controlla_compatibilita",
    "posso mangiare questo alimento": "controlla_compatibilita",
    "spiegami il motivo": "spiega_compatibilita",
    "spiegami il motivo della compatibilita": "spiega_compatibilita",
    "quali dati hai confrontato": "dati_controllo",
    "quali dati del profilo hai confrontato": "dati_controllo",

    # Allergeni
    "quali allergeni contiene": "chiedi_allergeni",
    "che allergeni contiene": "chiedi_allergeni",
    "contiene glutine": "contiene_glutine",
    "contiene lattosio": "contiene_lattosio",
    "contiene uova": "contiene_uova",

    # Profilo utente
    "utente riconosciuto": "info_profilo",
    "quale utente hai riconosciuto": "info_profilo",
    "le mie incompatibilita": "info_profilo",
    "quali allergie o intolleranze risultano nel mio profilo": "info_profilo",
    "eta registrata": "info_profilo",
    "qual e l eta registrata nel mio profilo": "info_profilo",

    # Riconoscimento attuale
    "alimento selezionato": "alimento_corrente",
    "che alimento e selezionato": "alimento_corrente",
    "come funziona il riconoscimento": "info_modelli",
    "come funziona il riconoscimento di utenti e alimenti": "info_modelli",
    "perche piu rilevamenti": "info_modelli",
    "perche il sistema richiede piu rilevamenti consecutivi": "info_modelli",

    # Informazioni sul progetto
    "progetto in breve": "info_progetto",
    "spiegami il progetto in breve": "info_progetto",
    "moduli del progetto": "moduli",
    "quali sono i moduli del progetto": "moduli",
    "sviluppi futuri": "info_progetto",
    "quali miglioramenti futuri si potrebbero aggiungere": "info_progetto",
}

INTENT_CONVERSAZIONALI_LOCALI = {
    "ripeti_risposta",
    "semplifica_risposta",
    "riassumi_risposta",
    "ringraziamento",
    "saluti",
    "conversazione",
}

ESEMPI_INTENT_SEMANTICI: dict[str, list[str]] = {
    "controlla_compatibilita": [
        "Questo alimento va bene per me?",
        "Secondo te questo prodotto potrebbe crearmi problemi?",
        "Posso consumare il prodotto selezionato?",
        "È adatto alla persona riconosciuta?",
        "Questo cibo è compatibile con il mio profilo?",
        "Dovrei evitare questo alimento?",
    ],
    "spiega_compatibilita": [
        "Per quale motivo posso o non posso mangiarlo?",
        "Spiegami perché il prodotto è compatibile oppure no",
        "Come mai questo alimento non va bene per me?",
        "Perché hai dato questo risultato sulla compatibilità?",
    ],
    "dati_controllo": [
        "Quali informazioni hai confrontato?",
        "Che dati del prodotto e del profilo hai usato?",
        "Su quali dati si basa il controllo?",
        "Cosa hai confrontato per decidere?",
    ],
    "richiedi_alternative": [
        "Cosa posso prendere al posto di questo prodotto?",
        "Suggeriscimi qualcosa di diverso",
        "Consigliami un sostituto adatto",
        "Che cosa potrei mangiare invece?",
        "Proponimi un prodotto alternativo",
    ],
    "altra_alternativa": [
        "Questa proposta non mi piace, dammene un'altra",
        "Hai un'altra opzione?",
        "Suggeriscimi una soluzione diversa dalla precedente",
        "Passa alla prossima alternativa",
        "Dammi un'altra alternativa",
        "Vorrei un'altra proposta",
        "Fammi vedere un sostituto diverso",
    ],
    "lista_alternative": [
        "Fammi vedere tutte le opzioni disponibili",
        "Quali sostituti sono presenti?",
        "Elencami tutte le alternative",
        "Mostrami tutte le possibilità",
    ],
    "spiega_alternativa": [
        "Perché hai scelto proprio questa alternativa?",
        "Come mai questa proposta è adatta al mio profilo?",
        "Spiegami il motivo del sostituto consigliato",
        "Perché dovrei scegliere questa opzione?",
    ],
    "chiedi_allergeni": [
        "Ci sono sostanze allergeniche in questo prodotto?",
        "Quali allergeni sono presenti?",
        "Questo alimento contiene ingredienti problematici?",
        "Dimmi gli allergeni del prodotto selezionato",
        "A cosa potrei essere allergico in questo alimento?",
    ],
    "info_profilo": [
        "Quali informazioni ci sono nel mio profilo?",
        "Che allergie e intolleranze risultano?",
        "Chi è la persona riconosciuta?",
        "Dimmi i dati dell'utente attivo",
        "Qual è l'età registrata?",
    ],
    "alimento_corrente": [
        "Che prodotto hai riconosciuto?",
        "Quale alimento è attualmente selezionato?",
        "Cosa vede la webcam in questo momento?",
        "Che cibo è stato rilevato?",
    ],
    "info_modelli": [
        "Come avviene il riconoscimento visivo?",
        "Quali modelli di intelligenza artificiale usate?",
        "Come riconoscete il volto e il cibo?",
        "Perché servono più rilevamenti consecutivi?",
        "Il riconoscimento viene eseguito nel browser?",
    ],
    "info_progetto": [
        "Spiegami in breve Smart Pantry",
        "A cosa serve questo progetto?",
        "Qual è l'obiettivo dell'applicazione?",
        "Che cosa fa Smart Pantry Tutor?",
        "Quali sviluppi futuri sono possibili?",
    ],
    "moduli": [
        "Quali sono i moduli del progetto?",
        "Da quali parti è composto il sistema?",
        "Quali componenti funzionali avete sviluppato?",
        "Come è organizzato il progetto?",
    ],
    "funzionamento": [
        "Descrivimi il flusso completo del sistema",
        "Che cosa succede dal riconoscimento alla risposta?",
        "Come lavora l'applicazione passo dopo passo?",
        "Qual è il funzionamento generale?",
    ],
    "info_database": [
        "Che ruolo svolge MySQL?",
        "Dove sono memorizzati profili e prodotti?",
        "Come comunica Flask con il database?",
        "Da dove vengono prese le alternative?",
    ],
    "limiti_privacy": [
        "Le immagini della webcam vengono salvate?",
        "Quali sono i limiti del riconoscimento?",
        "Il sistema può sbagliare?",
        "Come viene protetta la privacy?",
        "Posso fidarmi senza controllare l'etichetta?",
    ],
}


def nuova_sessione() -> dict[str, Any]:
    return {
        "utente": "",
        "alimento": "",
        "indice_alternativa": 0,
        "ultimo_utente_alternativa": "",
        "ultimo_alimento_alternativa": "",
        "ultima_alternativa_proposta": "",
        "ultimo_messaggio_utente": "",
        "ultimo_intent": "",
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


def prendi_tutti_prodotti() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM prodotti ORDER BY nome")
        return list(cursor.fetchall() or [])
    finally:
        cursor.close()
        conn.close()


def valore_booleano(valore: Any) -> bool:
    if isinstance(valore, bool):
        return valore

    if valore is None:
        return False

    return str(valore).strip().lower() in {
        "1",
        "true",
        "si",
        "sì",
        "yes",
    }


def valori_reali_profilo(valore: Any) -> list[str]:
    valori = testo_in_lista(valore)
    assenti = {"", "nessuna", "nessuno", "no", "non presente"}
    return [elemento for elemento in valori if elemento not in assenti]


def motivi_incompatibilita_estesi(
    utente: dict[str, Any],
    prodotto: dict[str, Any],
) -> list[str]:
    motivi = list(controlla_rischio(utente, prodotto))

    try:
        eta = int(utente.get("eta") or 0)
    except (TypeError, ValueError):
        eta = 0

    if eta and eta < 18 and valore_booleano(prodotto.get("alcool")):
        motivi.append("prodotto alcolico non adatto a un minorenne")

    return sorted(set(motivi))


def confronta_valori_profilo(
    valori_profilo: list[str],
    allergeni_prodotto: list[str],
) -> list[str]:
    corrispondenze: list[str] = []

    for valore in valori_profilo:
        for allergene in allergeni_prodotto:
            if valore in allergene or allergene in valore:
                corrispondenze.append(valore)

    return sorted(set(corrispondenze))


def dettaglio_verifica_personalizzata(
    utente: dict[str, Any],
    prodotto: dict[str, Any],
) -> dict[str, Any]:
    allergie = valori_reali_profilo(utente.get("allergia"))
    intolleranze = valori_reali_profilo(utente.get("intolleranza"))
    allergeni = testo_in_lista(prodotto.get("allergene"))

    allergie_corrispondenti = confronta_valori_profilo(allergie, allergeni)
    intolleranze_corrispondenti = confronta_valori_profilo(
        intolleranze,
        allergeni,
    )

    try:
        eta = int(utente.get("eta") or 0)
    except (TypeError, ValueError):
        eta = 0

    blocco_eta = bool(
        eta
        and eta < 18
        and valore_booleano(prodotto.get("alcool"))
    )

    motivi: list[str] = []

    for valore in allergie_corrispondenti:
        motivi.append(f"allergia registrata a {valore}")

    for valore in intolleranze_corrispondenti:
        motivi.append(f"intolleranza registrata a {valore}")

    if blocco_eta:
        motivi.append("prodotto alcolico non adatto a un minorenne")

    return {
        "esito": "incompatibile" if motivi else "compatibile",
        "allergie_corrispondenti": allergie_corrispondenti,
        "intolleranze_corrispondenti": intolleranze_corrispondenti,
        "blocco_eta": blocco_eta,
        "motivi_specifici": motivi,
    }


def serializza_utente_ai(utente: dict[str, Any] | None) -> dict[str, Any] | None:
    if not utente:
        return None

    return {
        "nome": str(utente.get("nome") or ""),
        "eta": utente.get("eta"),
        "allergie": valori_reali_profilo(utente.get("allergia")),
        "intolleranze": valori_reali_profilo(utente.get("intolleranza")),
    }


def serializza_prodotto_ai(
    prodotto: dict[str, Any],
    utente: dict[str, Any] | None = None,
) -> dict[str, Any]:
    nome_db = str(prodotto.get("nome") or "").strip()
    dati = {
        "nome": nome_alimento(nome_db),
        "nome_database": nome_db,
        "categoria": str(prodotto.get("categoria") or "").strip(),
        "allergeni": testo_in_lista(prodotto.get("allergene")),
        "alcool": valore_booleano(prodotto.get("alcool")),
        "alternative_registrate": prendi_alternative(prodotto),
    }

    if utente:
        verifica = dettaglio_verifica_personalizzata(utente, prodotto)
        motivi = motivi_incompatibilita_estesi(utente, prodotto)

        dati["compatibile_con_utente"] = verifica["esito"] == "compatibile"
        dati["motivi_incompatibilita"] = motivi
        dati["verifica_personalizzata"] = verifica

    return dati


def costruisci_contesto_openai(
    sessione: dict[str, Any],
    domanda: str = "",
) -> dict[str, Any]:
    utente_nome = str(sessione.get("utente", "")).strip()
    alimento_corrente = str(sessione.get("alimento", "")).strip()

    utente = prendi_utente(utente_nome) if utente_nome else None
    prodotti = prendi_tutti_prodotti()

    prodotti_serializzati = [
        serializza_prodotto_ai(prodotto, utente)
        for prodotto in prodotti
    ]

    prodotto_corrente = None
    alimento_menzionato = trova_alimento(domanda)
    prodotto_menzionato = None

    for prodotto in prodotti:
        nome_prodotto = str(prodotto.get("nome") or "").strip()

        if nome_prodotto.lower() == alimento_corrente.lower():
            prodotto_corrente = serializza_prodotto_ai(prodotto, utente)

        if alimento_menzionato and nome_prodotto.lower() == alimento_menzionato.lower():
            prodotto_menzionato = serializza_prodotto_ai(prodotto, utente)

    incompatibili = [
        {
            "nome": prodotto["nome"],
            "motivi": prodotto.get(
                "verifica_personalizzata",
                {},
            ).get("motivi_specifici", []),
            "allergeni": prodotto.get("allergeni", []),
            "alternative_registrate": prodotto.get(
                "alternative_registrate",
                [],
            ),
        }
        for prodotto in prodotti_serializzati
        if prodotto.get("compatibile_con_utente") is False
    ]

    compatibili = [
        prodotto["nome"]
        for prodotto in prodotti_serializzati
        if prodotto.get("compatibile_con_utente") is True
    ]

    history = list(sessione.get("history", []))
    # Il messaggio corrente è già presente nella history: non lo duplichiamo.
    history_precedente = history[:-1][-OPENAI_MAX_HISTORY_ITEMS:]

    return {
        "utente_attivo": serializza_utente_ai(utente),
        "alimento_corrente": nome_alimento(alimento_corrente) if alimento_corrente else None,
        "dettagli_alimento_corrente": prodotto_corrente,
        "alimento_menzionato_nella_domanda": (
            nome_alimento(alimento_menzionato) if alimento_menzionato else None
        ),
        "dettagli_alimento_menzionato": prodotto_menzionato,
        "regola_di_priorita": (
            "Se la domanda nomina un alimento, usa prima "
            "dettagli_alimento_menzionato. Altrimenti usa "
            "dettagli_alimento_corrente."
        ),
        "ultima_alternativa_proposta": (
            str(sessione.get("ultima_alternativa_proposta", "")).strip() or None
        ),
        "prodotti_incompatibili_con_utente": incompatibili,
        "prodotti_compatibili_con_utente": compatibili,
        "prodotti_registrati": prodotti_serializzati,
        "conversazione_precedente": history_precedente,
        "informazioni_progetto": {
            "nome": "Smart Pantry Tutor",
            "scopo": (
                "Riconoscere utente e alimento e fornire risposte personalizzate "
                "attraverso l'assistente conversazionale."
            ),
            "moduli_funzionali": [
                "riconoscimento utente",
                "riconoscimento alimento",
                "assistente conversazionale con chat e voce",
            ],
            "tecnologie": [
                "Flask",
                "MySQL",
                "BlazeFace",
                "Teachable Machine",
                "COCO-SSD",
                "TensorFlow.js",
                "Dialogflow",
                "OpenAI API",
            ],
            "privacy": (
                "Le immagini sono elaborate nel browser e non vengono salvate "
                "dal backend durante l'uso normale."
            ),
            "limiti": (
                "Il riconoscimento e il database sono dimostrativi. "
                "L'etichetta reale deve sempre essere controllata."
            ),
        },
    }


ISTRUZIONI_OPENAI = """
Sei l'assistente conversazionale di Smart Pantry Tutor.
Rispondi in italiano in modo semplice, breve, chiaro e diretto.

AMBITO
Puoi parlare soltanto di:
- profilo dell'utente riconosciuto;
- alimenti e bevande;
- allergeni, allergie, intolleranze e compatibilità;
- alternative alimentari;
- funzionamento, tecnologie, privacy e limiti di Smart Pantry.

STILE OBBLIGATORIO
1. Rispondi normalmente in 1 o 2 frasi.
2. Usa al massimo 3 frasi quando serve una precisazione importante.
3. Non ripetere informazioni già dette nella conversazione.
4. Non usare introduzioni come “stai chiedendo”, “alimento controllato”,
   “dati confrontati” o “esito finale”.
5. Non scrivere risposte da rapporto tecnico.
6. Quando ci sono più prodotti, usa un elenco breve.

DATI DEL PROGETTO
1. I moduli funzionali di Smart Pantry sono tre:
   - riconoscimento utente;
   - riconoscimento alimento;
   - assistente conversazionale con chat e voce.
2. Il controllo personalizzato del profilo non è un modulo autonomo.
3. MySQL è una tecnologia di supporto.
4. Per spiegare il riconoscimento, dì semplicemente che i modelli lavorano
   nel browser e il backend riceve i dati necessari per consultare MySQL.
   Non inserire esempi tra parentesi se non vengono richiesti.

REGOLE SUGLI ALIMENTI
1. Per i prodotti presenti nel CONTENUTO SMART PANTRY, usa sempre i dati del
   database come fonte principale.
2. Se un alimento comune non è presente nel database, puoi usare la tua
   conoscenza generale per indicare gli allergeni tipicamente presenti.
3. In questo caso devi essere prudente:
   - usa formule come “in genere”, “di solito” o “può contenere”;
   - ricorda che ricetta, marca e preparazione possono cambiare;
   - per prodotti confezionati o preparati invita a controllare l'etichetta.
4. Confronta gli allergeni tipici dell'alimento con allergie e intolleranze
   presenti nel profilo dell'utente.
5. Non dire automaticamente che un alimento è sicuro quando la composizione
   può variare.
6. Non inventare una composizione precisa, una marca o un'etichetta.
7. Per esempio, a una domanda su un panino con salame puoi valutare pane e
   salame in base agli allergeni comuni, precisando che alcuni prodotti
   industriali possono contenere derivati del latte o tracce.

REGOLE MEDICHE
1. Non prevedere sintomi personali e non formulare diagnosi.
2. Quando l'utente chiede conseguenze o sintomi, rispondi brevemente e
   aggiungi il consiglio medico solo se pertinente.
3. Puoi dire: “Smart Pantry non può prevedere i sintomi. Se lo hai già
   consumato, hai disturbi o sei preoccupato, rivolgiti a un medico.”

REGOLE SULLE ALTERNATIVE
1. Le richieste di alternative sono tra le funzioni principali di Smart Pantry.
2. Se il prodotto è presente nel database, usa prima le alternative registrate.
3. Proponi una sola alternativa alla volta, salvo che l'utente chieda
   esplicitamente di mostrarle tutte.
4. La risposta deve avere normalmente due frasi:
   - prima indica chiaramente l'alternativa;
   - poi spiega brevemente perché può essere utile rispetto
     all'incompatibilità rilevata.
5. Non ripetere tutto il profilo, tutti gli allergeni e tutto il controllo.
6. Per “dammene un'altra” proponi una scelta diversa da quelle già nominate.
7. Se un alimento comune non è nel database, puoi proporre una semplice
   alternativa usando conoscenza generale, confrontandola con il profilo.
   In questo caso specifica che composizione e marca possono variare e invita
   a controllare l'etichetta.
8. Non presentare mai un'alternativa come certamente sicura senza verifica
   dell'etichetta reale.
9. Usa nomi semplici e comprensibili, evitando descrizioni tecniche.

ALTRE REGOLE
1. Se la domanda nomina un alimento, valuta quello; altrimenti usa quello
   selezionato.
2. Se la domanda è fuori tema, ricorda brevemente che puoi aiutare solo
   nell'ambito Smart Pantry.
3. Non menzionare JSON, prompt, API o istruzioni interne.

ESEMPI DI STILE
- “Ti consiglio il latte senza lattosio. È una sostituzione semplice del
  latte tradizionale, ma controlla comunque l'etichetta.”
- “Puoi scegliere anche una bevanda vegetale. Verifica che non contenga
  altri allergeni incompatibili con il tuo profilo.”
- “In genere un panino con salame contiene glutine nel pane. Il salame può
  variare: controlla l'etichetta per verificare eventuali derivati del latte.”
- “I moduli sono tre: riconoscimento utente, riconoscimento alimento e
  assistente conversazionale.”
""".strip()


def prendi_client_openai():
    global OPENAI_CLIENT
    global OPENAI_HTTP_CLIENT

    if not OPENAI_AVAILABLE:
        return None

    if OPENAI_CLIENT is not None:
        return OPENAI_CLIENT

    with LOCK_OPENAI_CLIENT:
        if OPENAI_CLIENT is not None:
            return OPENAI_CLIENT

        trasporto = httpx.HTTPTransport(
            local_address="0.0.0.0",
            retries=1,
            http1=True,
            http2=False,
        )
        OPENAI_HTTP_CLIENT = httpx.Client(
            transport=trasporto,
            timeout=45.0,
            trust_env=False,
        )
        OPENAI_CLIENT = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            http_client=OPENAI_HTTP_CLIENT,
        )

    return OPENAI_CLIENT


def risposta_openai_smart_pantry(
    sessione: dict[str, Any],
    domanda: str,
) -> str | None:
    client = prendi_client_openai()

    if client is None:
        return None

    try:
        contesto = costruisci_contesto_openai(sessione, domanda)
        input_utente = (
            "CONTENUTO SMART PANTRY (dati affidabili):\n"
            + json.dumps(
                contesto,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            + "\n\nDOMANDA DELL'UTENTE:\n"
            + domanda
        )

        parametri = {
            "model": OPENAI_MODEL,
            "instructions": ISTRUZIONI_OPENAI,
            "input": input_utente,
            "max_output_tokens": 280,
            "store": False,
        }

        try:
            risposta = client.responses.create(
                **parametri,
                reasoning={"effort": "minimal"},
            )
        except BadRequestError:
            # Compatibilità con eventuali modelli che non accettano
            # l'opzione reasoning.
            risposta = client.responses.create(**parametri)

        testo = str(risposta.output_text or "").strip()

        if not testo:
            return None

        return testo[:1100]
    except Exception as error:
        # Se OpenAI non è raggiungibile, il backend usa automaticamente
        # Dialogflow, regole locali e classificatore semantico.
        app.logger.warning("OpenAI non disponibile: %s", error)
        return None


def normalizza_comando_rapido(testo: str) -> str:
    testo_norm = normalizza_testo(testo)
    testo_norm = testo_norm.replace("'", " ")
    testo_norm = re.sub(r"[^a-z0-9 ]+", " ", testo_norm)
    testo_norm = re.sub(r"\s+", " ", testo_norm)
    return testo_norm.strip()


def intent_locale_prioritario(testo: str) -> tuple[str, float]:
    testo_norm = normalizza_comando_rapido(testo)

    if testo_norm in COMANDI_RAPIDI_ESATTI:
        return COMANDI_RAPIDI_ESATTI[testo_norm], 1.0

    if testo_norm.startswith("richiedi alternative per "):
        return "richiedi_alternative", 1.0

    intent_locale, confidence_locale = classifica_intento_locale(testo)

    if intent_locale in INTENT_CONVERSAZIONALI_LOCALI:
        return intent_locale, confidence_locale

    return "", 0.0


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

    # Corregge piccoli refusi soltanto nelle parole principali del progetto.
    parole_dominio = {
        "alternativa",
        "alternative",
        "allergene",
        "allergeni",
        "allergia",
        "allergie",
        "compatibile",
        "compatibilita",
        "intolleranza",
        "intolleranze",
        "profilo",
        "alimento",
        "prodotto",
        "riconoscimento",
        "progetto",
    }

    parole_corrette: list[str] = []

    for parola in testo.split():
        parola_pulita = re.sub(r"[^a-z0-9']", "", parola)

        if len(parola_pulita) >= 6 and parola_pulita not in parole_dominio:
            vicine = get_close_matches(
                parola_pulita,
                parole_dominio,
                n=1,
                cutoff=0.78,
            )

            if vicine:
                parola = parola.replace(parola_pulita, vicine[0])

        parole_corrette.append(parola)

    return " ".join(parole_corrette)


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


def prepara_controllo_profilo(
    sessione: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
    utente_nome, alimento = risolvi_contesto(sessione)

    if not utente_nome or not alimento:
        return utente_nome, alimento, None, None

    return (
        utente_nome,
        alimento,
        prendi_utente(utente_nome),
        prendi_prodotto(alimento),
    )


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
            f"Sì: {nome_alimento(alimento)} risulta compatibile con il profilo "
            f"di {utente['nome']}. Non sono registrati allergeni principali."
        )

    if not rischi:
        return (
            f"Sì: {nome_alimento(alimento)} risulta compatibile con il profilo "
            f"di {utente['nome']}. Non ho rilevato incompatibilità dirette."
        )

    return (
        f"No: {nome_alimento(alimento)} non risulta compatibile con il profilo "
        f"di {utente['nome']}. Incompatibilità rilevata: {', '.join(rischi)}."
    )


def risposta_motivo_compatibilita(sessione: dict[str, Any]) -> str:
    utente_nome, alimento, utente, prodotto = prepara_controllo_profilo(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente, così posso spiegare il controllo."

    if not alimento:
        return "Prima seleziona un alimento da controllare."

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    allergeni = testo_in_lista(prodotto.get("allergene"))
    allergie = testo_in_lista(utente.get("allergia"))
    intolleranze = testo_in_lista(utente.get("intolleranza"))
    rischi = controlla_rischio(utente, prodotto)

    allergeni_testo = ", ".join(allergeni) if allergeni else "nessuno registrato"
    allergie_testo = ", ".join(allergie) if allergie else "nessuna"
    intolleranze_testo = ", ".join(intolleranze) if intolleranze else "nessuna"

    if rischi:
        return (
            f"Il motivo è questo: per {nome_alimento(alimento)} sono registrati "
            f"gli allergeni {allergeni_testo}; nel profilo di {utente['nome']} "
            f"risultano allergia {allergie_testo} e intolleranza "
            f"{intolleranze_testo}. La corrispondenza rilevata riguarda "
            f"{', '.join(rischi)}."
        )

    return (
        f"Il prodotto può contenere {allergeni_testo}, ma nel profilo di "
        f"{utente['nome']} risultano allergia {allergie_testo} e intolleranza "
        f"{intolleranze_testo}. Non è stata trovata alcuna corrispondenza diretta."
    )


def risposta_dati_controllo(sessione: dict[str, Any]) -> str:
    utente_nome, alimento, utente, prodotto = prepara_controllo_profilo(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente per vedere quali dati vengono confrontati."

    if not alimento:
        return "Prima seleziona un alimento da controllare."

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    allergeni = testo_in_lista(prodotto.get("allergene"))
    allergie = testo_in_lista(utente.get("allergia"))
    intolleranze = testo_in_lista(utente.get("intolleranza"))

    return (
        f"Ho confrontato gli allergeni registrati per {nome_alimento(alimento)} "
        f"({', '.join(allergeni) if allergeni else 'nessuno'}) con le allergie "
        f"({', '.join(allergie) if allergie else 'nessuna'}) e le intolleranze "
        f"({', '.join(intolleranze) if intolleranze else 'nessuna'}) presenti "
        f"nel profilo di {utente['nome']}."
    )


def formatta_alternativa(alternativa: str) -> str:
    """Rende leggibile il testo proveniente dal database."""
    testo = re.sub(r"\s+", " ", str(alternativa or "")).strip(" .,-")

    if not testo:
        return ""

    return testo[0].upper() + testo[1:]


def descrivi_rischi_alternativa(rischi: list[str]) -> str:
    if not rischi:
        return "l'incompatibilità rilevata"

    if len(rischi) == 1:
        return f"l'incompatibilità al {rischi[0]}"

    return "le incompatibilità a " + ", ".join(rischi)


def risposta_alternativa(
    sessione: dict[str, Any],
    continua: bool = False,
) -> str:
    utente_nome, alimento = risolvi_contesto(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente, così posso scegliere un'alternativa adatta."

    if not alimento:
        return "Prima seleziona l'alimento che vuoi sostituire."

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. "
            "Puoi comunque chiedermi un'alternativa scrivendo il nome completo del prodotto."
        )

    alternative = prendi_alternative(prodotto)
    rischi = controlla_rischio(utente, prodotto)

    if not rischi:
        return (
            f"{nome_alimento(alimento)} non risulta incompatibile con il tuo profilo. "
            "Posso comunque proporti un sostituto, ma non è necessario per motivi di compatibilità."
        )

    if not alternative:
        return (
            f"Non ci sono alternative registrate per {nome_alimento(alimento)}. "
            "Controlla l'etichetta e scegli un prodotto che non contenga "
            f"{', '.join(rischi)}."
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
            "Non ci sono altre alternative registrate per questo prodotto. "
            "Puoi scegliere una delle proposte precedenti, controllando sempre l'etichetta."
        )

    alternativa = formatta_alternativa(alternative[indice])
    sessione["ultima_alternativa_proposta"] = alternativa

    motivo = descrivi_rischi_alternativa(rischi)

    if indice == 0:
        return (
            f"Ti consiglio: {alternativa}. "
            f"È una sostituzione più adatta perché il prodotto originale presenta {motivo}; "
            "controlla comunque l'etichetta prima del consumo."
        )

    return (
        f"Puoi scegliere anche: {alternativa}. "
        f"È un'altra soluzione per evitare {motivo}; verifica comunque gli ingredienti."
    )



def risposta_motivo_alternativa(sessione: dict[str, Any]) -> str:
    utente_nome, alimento = risolvi_contesto(sessione)
    alternativa = formatta_alternativa(
        sessione.get("ultima_alternativa_proposta", "")
    )

    if not utente_nome:
        return "Prima riconosci l'utente."

    if not alimento:
        return "Prima seleziona un alimento."

    if not alternativa:
        return "Prima chiedimi un'alternativa."

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    rischi = controlla_rischio(utente, prodotto)
    motivo = descrivi_rischi_alternativa(rischi)

    return (
        f"Ti ho proposto {alternativa} perché sostituisce "
        f"{nome_alimento(alimento)}, che presenta {motivo}. "
        "È comunque importante controllare l'etichetta del prodotto scelto."
    )



def risposta_alternative_sicure(sessione: dict[str, Any]) -> str:
    utente_nome, alimento = risolvi_contesto(sessione)

    if not utente_nome:
        return "Prima riconosci l'utente."

    if not alimento:
        return "Prima seleziona l'alimento che vuoi sostituire."

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    if prodotto is None:
        return f"Non trovo {nome_alimento(alimento)} nel database."

    alternative = [
        formatta_alternativa(valore)
        for valore in prendi_alternative(prodotto)
        if formatta_alternativa(valore)
    ]
    rischi = controlla_rischio(utente, prodotto)

    if not alternative:
        return (
            f"Non ci sono alternative registrate per {nome_alimento(alimento)}. "
            "Scegli un prodotto senza gli allergeni incompatibili indicati nel tuo profilo."
        )

    elenco = "; ".join(
        f"{indice}. {alternativa}"
        for indice, alternativa in enumerate(alternative, start=1)
    )

    if rischi:
        return (
            f"Per sostituire {nome_alimento(alimento)} puoi scegliere: {elenco}. "
            f"Sono proposte pensate per evitare {descrivi_rischi_alternativa(rischi)}; "
            "controlla sempre l'etichetta."
        )

    return (
        f"Le alternative registrate per {nome_alimento(alimento)} sono: {elenco}. "
        "Scegli quella più adatta alle tue preferenze e verifica gli ingredienti."
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


def risposta_personalizzazione(sessione: dict[str, Any]) -> str:
    utente_nome, _ = risolvi_contesto(sessione)

    if not utente_nome:
        return (
            "Prima riconosci l'utente, così posso spiegare "
            "come personalizzo la risposta."
        )

    utente = prendi_utente(utente_nome)

    if utente is None:
        return f"Non trovo il profilo di {utente_nome} nel database."

    return (
        f"Uso le allergie e le intolleranze registrate nel profilo di "
        f"{utente['nome']} e le confronto con gli allergeni dell'alimento. "
        "L'età viene considerata soltanto quando il prodotto richiede un "
        "controllo specifico, per esempio nel caso delle bevande alcoliche. "
        "Se rilevo un'incompatibilità, ne spiego il motivo e propongo "
        "alternative adatte; altrimenti segnalo che il prodotto risulta compatibile."
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
        "I moduli funzionali sono tre: riconoscimento utente, riconoscimento "
        "alimento e assistente conversazionale con chat e voce. "
        "Il controllo personalizzato e MySQL sono componenti di supporto, "
        "non moduli autonomi."
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
        "Smart Pantry riconosce il volto e gli alimenti direttamente nel browser. "
        "Il backend riceve solo i dati necessari per consultare MySQL e rispondere."
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


def risposta_spiega_meglio(sessione: dict[str, Any]) -> str:
    ultimo_intent = sessione.get("ultimo_intent", "")
    ultimo_messaggio = sessione.get("ultimo_messaggio_utente", "")
    ultima_risposta = sessione.get("ultima_risposta", "")

    if not ultima_risposta:
        return (
            "Non ho ancora una risposta precedente da approfondire. "
            "Fammi prima una domanda su Smart Pantry."
        )

    if ultimo_intent in {
        "controlla_compatibilita",
        "spiega_compatibilita",
        "dati_controllo",
    }:
        return risposta_motivo_compatibilita(sessione)

    if ultimo_intent in {
        "richiedi_alternative",
        "altra_alternativa",
        "lista_alternative",
        "spiega_alternativa",
    } and sessione.get("ultima_alternativa_proposta"):
        return risposta_motivo_alternativa(sessione)

    if ultimo_intent == "info_progetto":
        return (
            "Smart Pantry Tutor è un assistente che unisce riconoscimento visivo "
            "e dati personali. Prima identifica l'utente e l'alimento, poi consulta "
            "il profilo e le informazioni presenti in MySQL. Infine comunica se il "
            "prodotto risulta compatibile e, quando necessario, propone alternative."
        )

    if ultimo_intent == "funzionamento":
        return (
            "In pratica il sistema lavora in quattro passaggi: riconosce l'utente, "
            "riconosce l'alimento, confronta allergeni e profilo nel database e "
            "restituisce una risposta personalizzata attraverso la chat."
        )

    if ultimo_intent == "moduli":
        return risposta_moduli()

    if ultimo_intent == "info_modelli":
        return risposta_modelli(ultimo_messaggio)

    if ultimo_intent == "info_database":
        return risposta_database(ultimo_messaggio)

    if ultimo_intent == "info_profilo":
        return risposta_utente(sessione, ultimo_messaggio)

    if ultimo_intent == "alimento_corrente":
        return risposta_alimento_corrente(sessione)

    return (
        "Certo, te lo riformulo in modo più chiaro: "
        + risposta_semplice(ultima_risposta)
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

    if any(frase in t for frase in (
        "spiega meglio",
        "spiegami meglio",
        "puoi spiegare meglio",
        "chiarisci meglio",
        "non ho capito bene",
        "approfondisci",
    )):
        return "spiega_meglio", 0.99

    if any(frase in t for frase in ("piu semplice", "spiegalo semplice", "semplifica")):
        return "semplifica_risposta", 0.94

    if any(frase in t for frase in ("riassumi", "in una frase", "brevemente")):
        return "riassumi_risposta", 0.94

    if any(frase in t for frase in ("grazie", "ti ringrazio")):
        return "ringraziamento", 0.98

    if any(frase in t for frase in ("ciao", "buongiorno", "buonasera", "alla prossima", "arrivederci", "a presto")):
        return "saluti", 0.97

    if any(frase in t for frase in (
        "perche questa alternativa",
        "perche e adatta a me",
        "motivo dell'alternativa",
        "spiegami questa alternativa",
    )):
        return "spiega_alternativa", 0.99

    if any(frase in t for frase in (
        "spiegami il motivo della compatibilita",
        "spiegami il motivo",
        "perche questo alimento non e compatibile",
        "perche non e compatibile",
        "motivo della compatibilita",
    )):
        return "spiega_compatibilita", 0.99

    if any(frase in t for frase in (
        "quali dati del profilo hai confrontato",
        "quali dati hai confrontato",
        "cosa hai confrontato",
        "dati del profilo confrontati",
    )):
        return "dati_controllo", 0.99

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
        "come usi il profilo",
        "come personalizzi",
        "personalizzare la risposta",
        "personalizzi i miei consigli",
    )):
        return "spiega_personalizzazione", 0.99

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


def carica_modello_semantico() -> bool:
    global MODELLO_SEMANTICO
    global EMBEDDING_ESEMPI
    global ETICHETTE_ESEMPI

    if not SEMANTIC_AVAILABLE:
        return False

    if MODELLO_SEMANTICO is not None and EMBEDDING_ESEMPI is not None:
        return True

    with LOCK_MODELLO_SEMANTICO:
        if MODELLO_SEMANTICO is not None and EMBEDDING_ESEMPI is not None:
            return True

        try:
            modello = SentenceTransformer(SEMANTIC_MODEL_NAME)
            frasi: list[str] = []
            etichette: list[str] = []

            for intent, esempi in ESEMPI_INTENT_SEMANTICI.items():
                for esempio in esempi:
                    frasi.append(esempio)
                    etichette.append(intent)

            embedding = modello.encode(
                frasi,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            MODELLO_SEMANTICO = modello
            EMBEDDING_ESEMPI = embedding
            ETICHETTE_ESEMPI = etichette
            return True
        except Exception as error:
            app.logger.warning(
                "Classificatore semantico non disponibile: %s",
                error,
            )
            return False


def classifica_intento_semantico(testo: str) -> tuple[str, float]:
    testo = str(testo or "").strip()

    if len(testo) < 4 or not carica_modello_semantico():
        return "fallback", 0.0

    try:
        vettore_domanda = MODELLO_SEMANTICO.encode(
            testo,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        punteggi = util.cos_sim(
            vettore_domanda,
            EMBEDDING_ESEMPI,
        )[0]

        migliori_per_intent: dict[str, float] = {}

        for indice, etichetta in enumerate(ETICHETTE_ESEMPI):
            punteggio = float(punteggi[indice])
            precedente = migliori_per_intent.get(etichetta, -1.0)

            if punteggio > precedente:
                migliori_per_intent[etichetta] = punteggio

        classifica = sorted(
            migliori_per_intent.items(),
            key=lambda elemento: elemento[1],
            reverse=True,
        )

        if not classifica:
            return "fallback", 0.0

        intent_migliore, punteggio_migliore = classifica[0]
        secondo_punteggio = classifica[1][1] if len(classifica) > 1 else 0.0
        margine = punteggio_migliore - secondo_punteggio

        if (
            punteggio_migliore >= SEMANTIC_THRESHOLD
            and margine >= SEMANTIC_MARGIN
        ):
            return intent_migliore, punteggio_migliore

        return "fallback", punteggio_migliore
    except Exception as error:
        app.logger.warning(
            "Errore durante la classificazione semantica: %s",
            error,
        )
        return "fallback", 0.0


def classifica_followup(
    sessione: dict[str, Any],
    testo: str,
) -> tuple[str, float]:
    t = normalizza_testo(testo)
    ultimo_intent = sessione.get("ultimo_intent", "")

    richieste_motivo = {
        "perche",
        "e perche",
        "come mai",
        "spiegami meglio",
        "qual e il motivo",
    }

    if t in richieste_motivo:
        if ultimo_intent in {
            "richiedi_alternative",
            "altra_alternativa",
            "lista_alternative",
            "spiega_alternativa",
        } or sessione.get("ultima_alternativa_proposta"):
            return "spiega_alternativa", 0.99

        if ultimo_intent in {
            "controlla_compatibilita",
            "spiega_compatibilita",
            "dati_controllo",
        }:
            return "spiega_compatibilita", 0.99

    if t in {
        "e un altra",
        "un altra",
        "ancora",
        "prossima",
        "un altra opzione",
    } and sessione.get("ultima_alternativa_proposta"):
        return "altra_alternativa", 0.99

    if t in {
        "e tutte",
        "mostramele tutte",
        "fammi vedere tutte",
        "quali sono tutte",
    }:
        return "lista_alternative", 0.99

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

    if intent == "spiega_meglio":
        return risposta_spiega_meglio(sessione), True

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

    if intent == "spiega_alternativa":
        return risposta_motivo_alternativa(sessione), True

    if intent == "spiega_compatibilita":
        return risposta_motivo_compatibilita(sessione), True

    if intent == "dati_controllo":
        return risposta_dati_controllo(sessione), True

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

    if intent == "spiega_personalizzazione":
        return risposta_personalizzazione(sessione), True

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
            "semantic": SEMANTIC_AVAILABLE,
            "semantic_model": SEMANTIC_MODEL_NAME if SEMANTIC_AVAILABLE else "",
            "openai": OPENAI_AVAILABLE,
            "openai_model": OPENAI_MODEL if OPENAI_AVAILABLE else "",
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

    source = "locale"
    intent = ""
    confidence = 0.0
    risposta = ""
    understood = False
    fulfillment_text = ""

    # I comandi rapidi e i controlli della conversazione restano locali.
    intent_prioritario, confidence_prioritaria = intent_locale_prioritario(
        user_message
    )

    if intent_prioritario:
        intent = intent_prioritario
        confidence = confidence_prioritaria
        risposta, understood = esegui_intento(
            intent,
            user_message,
            sessione,
        )

    # Tutte le altre domande pertinenti vengono interpretate da OpenAI
    # utilizzando profilo, prodotti, compatibilità e cronologia reali.
    if not intent and OPENAI_AVAILABLE:
        risposta_ai = risposta_openai_smart_pantry(
            sessione,
            user_message,
        )

        if risposta_ai:
            risposta = risposta_ai
            understood = True
            intent = "conversazione_smart_pantry"
            confidence = 1.0
            source = "openai"

    # Piano di riserva gratuito: Dialogflow, regole e Sentence Transformers.
    if not intent:
        intent_locale, confidence_locale = classifica_intento_locale(user_message)
        intent_specifici = {
            "spiega_alternativa",
            "spiega_compatibilita",
            "dati_controllo",
            "spiega_personalizzazione",
            "spiega_meglio",
        }

        dialogflow_result = rileva_intent_dialogflow(user_message, session_id)

        if intent_locale in intent_specifici:
            intent = intent_locale
            confidence = confidence_locale
        elif (
            dialogflow_result
            and not dialogflow_result["is_fallback"]
            and dialogflow_result["canonical_intent"]
        ):
            intent = dialogflow_result["canonical_intent"]
            confidence = dialogflow_result["confidence"]
            fulfillment_text = dialogflow_result["fulfillment_text"]
            source = "dialogflow"
        elif intent_locale != "fallback":
            intent = intent_locale
            confidence = confidence_locale

        if not intent:
            intent_followup, confidence_followup = classifica_followup(
                sessione,
                user_message,
            )

            if intent_followup != "fallback":
                intent = intent_followup
                confidence = confidence_followup
                source = "contesto"

        if not intent:
            intent_semantico, confidence_semantica = classifica_intento_semantico(
                user_message,
            )

            if intent_semantico != "fallback":
                intent = intent_semantico
                confidence = confidence_semantica
                source = "semantico"

        if not intent:
            intent = "fallback"
            confidence = 0.0

        risposta, understood = esegui_intento(
            intent,
            user_message,
            sessione,
        )

        # Se Dialogflow riconosce un intent non mappato ma possiede una
        # risposta valida, usiamo il fulfillment.
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

    if understood and intent != "ripeti_risposta":
        sessione["ultimo_intent"] = intent

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
            "semantic_enabled": SEMANTIC_AVAILABLE,
            "openai_enabled": OPENAI_AVAILABLE,
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
