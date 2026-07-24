from sentence_transformers import SentenceTransformer, util

modello = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

intenti = {
    "compatibilita": [
        "Posso mangiare questo alimento?",
        "Questo prodotto va bene per me?",
        "Questo cibo potrebbe crearmi problemi?",
    ],
    "alternative": [
        "Dammi un'alternativa",
        "Cosa posso mangiare al posto di questo?",
        "Suggeriscimi un prodotto diverso",
    ],
    "allergeni": [
        "Quali allergeni contiene?",
        "Ci sono ingredienti allergenici?",
        "Contiene sostanze a cui potrei essere allergico?",
    ],
    "profilo": [
        "Quali allergie ho?",
        "Che dati ci sono nel mio profilo?",
        "Chi hai riconosciuto?",
    ],
}

domanda = "Secondo te questo prodotto potrebbe crearmi problemi?"

vettore_domanda = modello.encode(
    domanda,
    convert_to_tensor=True,
    normalize_embeddings=True,
)

risultati = []

for nome_intent, esempi in intenti.items():
    vettori_esempi = modello.encode(
        esempi,
        convert_to_tensor=True,
        normalize_embeddings=True,
    )

    punteggi = util.cos_sim(vettore_domanda, vettori_esempi)[0]
    punteggio_migliore = float(punteggi.max())

    risultati.append((nome_intent, punteggio_migliore))

risultati.sort(key=lambda elemento: elemento[1], reverse=True)

for nome_intent, punteggio in risultati:
    print(f"{nome_intent}: {punteggio:.3f}")