from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    "host": "localhost",
    "user": "smart_user",
    "password": "smartpass",
    "database": "smart_pantry"
}

ultimo_utente = "Pasquale"
ultimo_alimento = ""

indice_alternativa = 0
ultimo_utente_alternativa = ""
ultimo_alimento_alternativa = ""

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
    "cracker"
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
    "cracker": "cracker"
}


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def nome_alimento(alimento):
    if alimento is None:
        return ""

    return NOMI_ALIMENTI.get(alimento, alimento)


def normalizza_testo(testo):
    if testo is None:
        return ""

    testo = str(testo).lower().strip()

    testo = testo.replace("’", "'")
    testo = testo.replace("‘", "'")
    testo = testo.replace("`", "'")
    testo = testo.replace("è", "e")

    testo = testo.replace("torta", "cake")
    testo = testo.replace("uovo", "uova")

    return testo


def trova_utente(testo):
    testo = testo.lower()

    if "pasquale" in testo:
        return "Pasquale"

    if "carmine" in testo:
        return "Carmine"

    if "francesco" in testo:
        return "Francesco"

    return ""


def trova_alimento(testo):
    testo = normalizza_testo(testo)

    for alimento in ALIMENTI:
        if alimento in testo:
            return alimento

    return ""


def richiesta_alternativa(testo):
    testo = testo.lower()

    parole = [
        "alternativa",
        "alternative",
        "al posto",
        "cosa posso mangiare",
        "consigliami",
        "suggeriscimi",
        "non posso mangiare",
        "senza glutine",
        "senza lattosio",
        "senza latte",
        "senza uova"
    ]

    return any(parola in testo for parola in parole)

def richiesta_lista_alternative(testo):
    testo = normalizza_testo(testo)

    parole = [
        "alternative sicure",
        "tutte le alternative",
        "mostrami tutte le alternative",
        "elenco alternative",
        "quali alternative",
        "fammi vedere le alternative"
    ]

    return any(parola in testo for parola in parole)
def richiesta_altra_alternativa(testo):
    testo = normalizza_testo(testo)

    parole = [
        "non mi piace",
        "dimmene un'altra",
        "dammene un'altra",
        "dammene un altra",
        "dimmene un altra",
        "un'altra",
        "un altra",
        "altra alternativa",
        "dammi un'altra",
        "dammi un altra",
        "non va bene",
        "qualcos'altro",
        "qualcos altro",
        "me ne dai un'altra",
        "me ne dai un altra",
        "me ne consigli un'altra",
        "me ne consigli un altra"
    ]

    return any(parola in testo for parola in parole)

def richiesta_compatibilita(testo):
    testo = testo.lower()

    parole = [
        "posso mangiare",
        "lo posso mangiare",
        "posso prenderlo",
        "posso prenderla",
        "è compatibile",
        "e compatibile",
        "compatibile con il mio profilo",
        "è sicuro",
        "e sicuro",
        "mi fa male",
        "va bene per me",
        "posso assumerlo",
        "posso assumerla"
    ]

    return any(parola in testo for parola in parole)


def richiesta_allergeni(testo):
    testo = testo.lower()

    parole = [
        "allergeni",
        "allergene",
        "contiene",
        "che cosa contiene",
        "cosa contiene",
        "ingredienti",
        "rischi"
    ]

    return any(parola in testo for parola in parole)


def prendi_utente(nome):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM utenti WHERE LOWER(nome) = LOWER(%s)",
        (nome,)
    )

    utente = cursor.fetchone()

    cursor.close()
    conn.close()

    return utente


def prendi_prodotto(nome):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM prodotti WHERE LOWER(nome) = LOWER(%s)",
        (nome,)
    )

    prodotto = cursor.fetchone()

    cursor.close()
    conn.close()

    return prodotto


def testo_in_lista(testo):
    if testo is None:
        return []

    if str(testo).strip() == "":
        return []

    return [
        elemento.strip().lower()
        for elemento in str(testo).split(",")
        if elemento.strip() != ""
    ]


def controlla_rischio(utente, prodotto):
    allergia_utente = testo_in_lista(utente.get("allergia"))
    intolleranza_utente = testo_in_lista(utente.get("intolleranza"))
    allergeni_prodotto = testo_in_lista(prodotto.get("allergene"))

    profilo_utente = allergia_utente + intolleranza_utente

    rischi = []

    for elemento in profilo_utente:
        for allergene in allergeni_prodotto:
            if elemento in allergene or allergene in elemento:
                rischi.append(elemento)

    return list(set(rischi))


def imposta_contesto(utente_nome="", alimento=""):
    global ultimo_utente
    global ultimo_alimento

    if utente_nome != "":
        ultimo_utente = utente_nome

    if alimento != "":
        ultimo_alimento = alimento


def risolvi_contesto(utente_nome="", alimento=""):
    global ultimo_utente
    global ultimo_alimento

    if utente_nome == "":
        utente_nome = ultimo_utente

    if alimento == "":
        alimento = ultimo_alimento

    if utente_nome == "":
        utente_nome = "Pasquale"

    return utente_nome, alimento


def risposta_compatibilita(utente_nome, alimento):
    utente_nome, alimento = risolvi_contesto(utente_nome, alimento)

    if alimento == "":
        return (
            "Prima seleziona un alimento con la webcam, oppure scrivimi il nome dell'alimento."
        )

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return "Non trovo questo utente nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. "
            "Quindi non posso controllarne la compatibilità."
        )

    allergene_prodotto = prodotto.get("allergene")

    if allergene_prodotto is None or str(allergene_prodotto).strip() == "":
        return (
            f"Sì, {utente['nome']}: {nome_alimento(alimento)} non ha allergeni principali registrati nel database."
        )

    rischi = controlla_rischio(utente, prodotto)

    if len(rischi) == 0:
        return (
            f"Sì, {utente['nome']}: {nome_alimento(alimento)} è compatibile con il tuo profilo. "
            f"Contiene o può contenere {allergene_prodotto}, ma questi elementi non risultano tra le tue allergie o intolleranze."
        )

    return (
        f"No, {utente['nome']}: {nome_alimento(alimento)} non è consigliato per il tuo profilo. "
        f"Può contenere {allergene_prodotto} e nel tuo profilo risulta incompatibilità con {', '.join(rischi)}."
    )

def prendi_alternative(prodotto):
    alternative = [
        prodotto.get("alternativa"),
        prodotto.get("alternativa2"),
        prodotto.get("alternativa3")
    ]

    return [
        alt for alt in alternative
        if alt is not None and str(alt).strip() != ""
    ]
def risposta_alternativa(utente_nome, alimento, continua=False):
    global ultimo_utente
    global ultimo_alimento

    global indice_alternativa
    global ultimo_utente_alternativa
    global ultimo_alimento_alternativa

    utente_nome, alimento = risolvi_contesto(utente_nome, alimento)

    if alimento == "":
        return (
            "Prima seleziona un alimento con la webcam. "
            "Poi posso suggerirti un'alternativa adatta al profilo utente."
        )

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return "Non trovo questo utente nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. "
            "Aggiungilo nella tabella prodotti per gestire allergeni e alternative."
        )

    ultimo_utente = utente_nome
    ultimo_alimento = alimento

    allergene_prodotto = prodotto.get("allergene")
    alternative = prendi_alternative(prodotto)

    if allergene_prodotto is None or str(allergene_prodotto).strip() == "":
        return (
            f"{utente['nome']}, {nome_alimento(alimento)} non ha allergeni principali registrati. "
            "Quindi non è necessaria un'alternativa specifica."
        )

    rischi = controlla_rischio(utente, prodotto)

    if len(rischi) == 0:
        return (
            f"{utente['nome']}, {nome_alimento(alimento)} può contenere {allergene_prodotto}, "
            "ma non risulta incompatibile con il tuo profilo. "
            "Puoi comunque controllare sempre l'etichetta reale del prodotto."
        )

    if len(alternative) == 0:
        return (
            f"{utente['nome']}, attenzione: {nome_alimento(alimento)} può contenere {allergene_prodotto}, "
            "ma non ho alternative registrate nel database."
        )

    stessa_richiesta = (
        ultimo_utente_alternativa == utente_nome
        and ultimo_alimento_alternativa == alimento
    )

    if not stessa_richiesta:
        ultimo_utente_alternativa = utente_nome
        ultimo_alimento_alternativa = alimento
        indice_alternativa = 0
    else:
        if continua:
            indice_alternativa += 1
        else:
            indice_alternativa = 0

    if indice_alternativa >= len(alternative):
        indice_alternativa = len(alternative) - 1

        elenco = ", ".join(alternative)

        return (
            f"Per {nome_alimento(alimento)} non ho altre alternative registrate oltre a queste: "
            f"{elenco}. Controlla sempre l'etichetta del prodotto."
        )

    rischio_testo = ", ".join(rischi)
    alternativa = alternative[indice_alternativa]

    if indice_alternativa == 0:
        return (
            f"{utente['nome']}, per {nome_alimento(alimento)} ho trovato un rischio legato a {rischio_testo}. "
            f"La prima alternativa consigliata è: {alternativa}."
        )

    return (
        f"Certo, ti propongo un'altra alternativa per {nome_alimento(alimento)}: "
        f"{alternativa}. È una possibile opzione da valutare al posto del prodotto originale."
    )

def risposta_alternative_sicure(utente_nome, alimento):
    utente_nome, alimento = risolvi_contesto(utente_nome, alimento)

    if alimento == "":
        return (
            "Prima seleziona un alimento con la webcam. "
            "Poi posso mostrarti tutte le alternative sicure disponibili."
        )

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return "Non trovo questo utente nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. "
            "Aggiungilo nella tabella prodotti per vedere le alternative."
        )

    allergene_prodotto = prodotto.get("allergene")
    alternative = prendi_alternative(prodotto)

    if len(alternative) == 0:
        return (
            f"Per {nome_alimento(alimento)} non ho alternative registrate nel database."
        )

    rischi = controlla_rischio(utente, prodotto)

    elenco = "; ".join(alternative)

    if len(rischi) > 0:
        return (
            f"Per {utente['nome']}, {nome_alimento(alimento)} può essere rischioso perché contiene {allergene_prodotto}. "
            f"Le alternative disponibili sono: {elenco}."
        )

    return (
        f"{nome_alimento(alimento)} non risulta incompatibile con il profilo di {utente['nome']}. "
        f"Comunque, nel database sono disponibili queste alternative: {elenco}."
    )

def risposta_allergeni(testo):
    global ultimo_utente
    global ultimo_alimento

    utente_nome = trova_utente(testo)
    alimento = trova_alimento(testo)

    if utente_nome == "":
        utente_nome = ultimo_utente

    if alimento == "":
        alimento = ultimo_alimento

    if alimento == "":
        return (
            "Dimmi l'alimento di cui vuoi conoscere gli allergeni. "
            "Per esempio: che allergeni ha la pizza?"
        )

    utente = prendi_utente(utente_nome)
    prodotto = prendi_prodotto(alimento)

    if utente is None:
        return "Non trovo questo utente nel database."

    if prodotto is None:
        return (
            f"Non trovo {nome_alimento(alimento)} nel database. "
            "Aggiungilo nella tabella prodotti per conoscere gli allergeni."
        )

    allergene = prodotto.get("allergene")

    if allergene is None or str(allergene).strip() == "":
        return (
            f"{nome_alimento(alimento)} non ha allergeni principali registrati nel database."
        )

    rischi = controlla_rischio(utente, prodotto)

    if len(rischi) > 0:
        return (
            f"Gli allergeni registrati per {nome_alimento(alimento)} sono: {allergene}. "
            f"Nel profilo di {utente['nome']} questi allergeni sono rilevanti perché c'è incompatibilità con {', '.join(rischi)}."
        )

    return (
        f"Gli allergeni registrati per {nome_alimento(alimento)} sono: {allergene}. "
        f"Per {utente['nome']} non risultano incompatibilità dirette."
    )


def risposta_progetto():
    return (
        "Smart Pantry Tutor è un sistema intelligente che riconosce l'utente, "
        "identifica alimenti tramite computer vision, consulta un database MySQL "
        "con profili utente e allergeni, e suggerisce alternative alimentari personalizzate."
    )


def risposta_funzionamento():
    return (
        "Il sistema funziona in quattro passaggi: prima riconosce l'utente tramite webcam, "
        "poi riconosce l'alimento, successivamente consulta il database MySQL e infine "
        "l'assistente restituisce una risposta personalizzata su allergeni, compatibilità e alternative."
    )


def risposta_modelli_alimenti():
    return (
        "Per gli alimenti uso due approcci: COCO-SSD per riconoscere oggetti alimentari già presenti nel dataset COCO, "
        "come pizza, banana, sandwich e torta, e un modello Teachable Machine personalizzato per alimenti importanti "
        "come latte, uova, pane, yogurt e cracker."
    )


def risposta_database():
    return (
        "Il database MySQL contiene i profili degli utenti, con allergie e intolleranze, "
        "e la tabella dei prodotti, con allergeni e alternative consigliate. "
        "Il backend Flask interroga il database per costruire la risposta personalizzata."
    )


def risposta_moduli():
    return (
        "I moduli principali sono: riconoscimento utente, riconoscimento alimento, controllo del database "
        "e assistente Smart Pantry. Flask e MySQL collegano la parte visiva alla risposta personalizzata."
    )


def risposta_utente():
    global ultimo_utente

    utente = prendi_utente(ultimo_utente)

    if utente is None:
        return "Non trovo l'utente nel database."

    allergia = utente.get("allergia")
    intolleranza = utente.get("intolleranza")

    allergia_testo = allergia if allergia else "nessuna"
    intolleranza_testo = intolleranza if intolleranza else "nessuna"

    return (
        f"Sei {utente['nome']}, hai {utente['eta']} anni. "
        f"Allergia: {allergia_testo}. "
        f"Intolleranza: {intolleranza_testo}."
    )


def risposta_alimento_corrente():
    global ultimo_alimento

    if ultimo_alimento == "":
        return "Al momento non c'è nessun alimento selezionato."

    return f"L'alimento selezionato è {nome_alimento(ultimo_alimento)}."


def risposta_locale(testo):
    global ultimo_utente
    global ultimo_alimento

    testo_norm = normalizza_testo(testo)

    utente_trovato = trova_utente(testo)
    alimento_trovato = trova_alimento(testo)

    if utente_trovato != "":
        ultimo_utente = utente_trovato

    if alimento_trovato != "":
        ultimo_alimento = alimento_trovato

    if "grazie" in testo_norm or "ti ringrazio" in testo_norm:
        return "Prego, sono qui per aiutarti."

    if (
        "ciao" in testo_norm
        or "arrivederci" in testo_norm
        or "alla prossima" in testo_norm
        or "a presto" in testo_norm
    ):
        return "Ciao, alla prossima."

    if (
        "come funziona" in testo_norm
        or "funzionamento" in testo_norm
    ):
        return risposta_funzionamento()

    if (
        "spiegami il progetto" in testo_norm
        or "cosa fa smart pantry" in testo_norm
        or "progetto" in testo_norm
    ):
        return risposta_progetto()

    if (
        "che modello usi" in testo_norm
        or "modelli alimenti" in testo_norm
        or "modello usi per gli alimenti" in testo_norm
        or "coco" in testo_norm
        or "teachable" in testo_norm
    ):
        return risposta_modelli_alimenti()

    if (
        "database" in testo_norm
        or "mysql" in testo_norm
        or "ruolo ha il database" in testo_norm
    ):
        return risposta_database()

    if (
        "moduli" in testo_norm
        or "quali sono i moduli" in testo_norm
        or "componenti" in testo_norm
    ):
        return risposta_moduli()

    if (
        "chi sono" in testo_norm
        or "mi riconosci" in testo_norm
        or "profilo utente" in testo_norm
    ):
        return risposta_utente()

    if (
        "che alimento è selezionato" in testo_norm
        or "che alimento e selezionato" in testo_norm
        or "alimento selezionato" in testo_norm
    ):
        return risposta_alimento_corrente()

    if richiesta_lista_alternative(testo):
        return risposta_alternative_sicure(ultimo_utente, ultimo_alimento)

    if richiesta_altra_alternativa(testo):
        return risposta_alternativa(ultimo_utente, ultimo_alimento, continua=True)

    if richiesta_alternativa(testo):
        return risposta_alternativa(ultimo_utente, ultimo_alimento, continua=False)

    if richiesta_allergeni(testo):
        return risposta_allergeni(testo)

    if richiesta_compatibilita(testo):
        return risposta_compatibilita(ultimo_utente, ultimo_alimento)

    return (
        "Puoi chiedermi alternative alimentari, allergeni, compatibilità con il profilo "
        "o informazioni sul progetto. Per esempio puoi dire: dammi alternative per pizza."
    )


@app.route("/", methods=["GET"])
def home():
    return "Backend Smart Pantry attivo e collegato al database."


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()

    user_message = data.get("message", "")
    user_name = data.get("user", "")
    food_name = data.get("food", "")

    global ultimo_utente
    global ultimo_alimento

    if user_name != "":
        ultimo_utente = user_name

    if food_name != "":
        ultimo_alimento = food_name

    print("Messaggio ricevuto:", user_message)
    print("Utente ricevuto:", user_name)
    print("Alimento ricevuto:", food_name)
    print("Ultimo utente:", ultimo_utente)
    print("Ultimo alimento:", ultimo_alimento)
    print("Indice alternativa:", indice_alternativa)

    risposta = risposta_locale(user_message)

    return jsonify({
        "reply": risposta
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )