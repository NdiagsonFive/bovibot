"""
BoviBot — Backend FastAPI
Gestion d'élevage bovin avec LLM (Groq) + PL/SQL
Projet L3 — ESP/UCAD
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
import os, re, json, httpx
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="BoviBot API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Configuration ───────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "bovibot"),
}
LLM_API_KEY  = os.getenv("OPENAI_API_KEY")
LLM_MODEL    = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")

# ── Schéma BDD pour le prompt ───────────────────────────────
DB_SCHEMA = """
Tables MySQL disponibles :
races(id, nom, origine, poids_adulte_moyen_kg, production_lait_litre_jour)
animaux(id, numero_tag, nom, race_id, sexe[M/F], date_naissance, poids_actuel, statut[actif/vendu/mort/quarantaine], mere_id, pere_id)
pesees(id, animal_id, poids_kg, date_pesee, agent)
sante(id, animal_id, type[vaccination/traitement/examen/chirurgie], description, date_acte, veterinaire, medicament, cout, prochain_rdv)
reproduction(id, mere_id, pere_id, date_saillie, date_velage_prevue, date_velage_reelle, nb_veaux, statut[en_gestation/vele/avortement/echec])
alimentation(id, animal_id, type_aliment, quantite_kg, date_alimentation, cout_unitaire_kg)
ventes(id, animal_id, acheteur, telephone_acheteur, date_vente, poids_vente_kg, prix_fcfa)
alertes(id, animal_id, type, message, niveau[info/warning/critical], date_creation, traitee)
historique_statut(id, animal_id, ancien_statut, nouveau_statut, date_changement)

Fonctions disponibles :
- fn_age_en_mois(animal_id) → INT
- fn_gmq(animal_id) → DECIMAL (gain moyen quotidien en kg/jour)

Procédures disponibles :
- sp_enregistrer_pesee(animal_id, poids_kg, date, agent)
- sp_declarer_vente(animal_id, acheteur, telephone, prix_fcfa, poids_vente_kg, date_vente)
"""

SYSTEM_PROMPT = f"""Tu es BoviBot, l'assistant IA d'un élevage bovin.
Tu aides l'éleveur à gérer son troupeau en langage naturel.

{DB_SCHEMA}

Tu peux répondre à deux types de demandes :
1. CONSULTATION : Requête SQL SELECT pour afficher des données
2. ACTION : Appel de procédure stockée (pesée, vente)

Réponds TOUJOURS avec un objet JSON valide et rien d'autre.
Pas de texte avant ou après le JSON. Pas de backticks. Pas de markdown.

Consultation : {{"type":"query","sql":"SELECT ...","explication":"..."}}
Action pesée : {{"type":"action","action":"sp_enregistrer_pesee","params":{{"animal_id":1,"poids_kg":320.5,"date":"2026-03-27","agent":"Nom"}},"explication":"...","confirmation":"Résumé pour confirmation"}}
Action vente  : {{"type":"action","action":"sp_declarer_vente","params":{{"animal_id":1,"acheteur":"Nom","telephone":"+221...","prix_fcfa":450000,"poids_vente_kg":310.0,"date_vente":"2026-03-27"}},"explication":"...","confirmation":"Résumé pour confirmation"}}
Info directe  : {{"type":"info","sql":null,"explication":"..."}}

RÈGLES STRICTES :
- Retourne UNIQUEMENT le JSON, rien d'autre
- Requêtes SELECT uniquement pour les consultations (LIMIT 100)
- Les actions nécessitent une confirmation explicite de l'utilisateur
- Toujours utiliser fn_age_en_mois() et fn_gmq() dans les requêtes pertinentes
- Dates au format YYYY-MM-DD
"""

# ── Connexion MySQL ─────────────────────────────────────────
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def execute_query(sql: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
                elif hasattr(v, '__float__'):
                    row[k] = float(v)
        return rows
    finally:
        cursor.close()
        conn.close()

def call_procedure(name: str, params: dict):
    conn = get_db()
    cursor = conn.cursor()
    try:
        if name == "sp_enregistrer_pesee":
            cursor.callproc("sp_enregistrer_pesee", [
                params["animal_id"], params["poids_kg"],
                params["date"], params.get("agent", "BoviBot")
            ])
        elif name == "sp_declarer_vente":
            cursor.callproc("sp_declarer_vente", [
                params["animal_id"], params["acheteur"],
                params.get("telephone", ""), params["prix_fcfa"],
                params.get("poids_vente_kg", 0), params["date_vente"]
            ])
        conn.commit()
        return {"success": True}
    finally:
        cursor.close()
        conn.close()

# ── Appel LLM (Groq) ────────────────────────────────────────
async def ask_llm(question: str, history: list = []) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history[-6:]
    messages.append({"role": "user", "content": question})

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0,
                "stream": False
            },
            timeout=30,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()

        # Nettoyer les backticks markdown
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        content = content.strip()

        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Réponse LLM non parseable : {content}")

# ── Modèle de requête ───────────────────────────────────────
class ChatMessage(BaseModel):
    question: str
    history: list = []
    confirm_action: bool = False
    pending_action: dict = {}

# ── Routes API ──────────────────────────────────────────────
@app.post("/api/chat")
async def chat(msg: ChatMessage):
    try:
        if msg.confirm_action and msg.pending_action:
            call_procedure(msg.pending_action["action"], msg.pending_action["params"])
            return {"type": "action_done", "answer": "✅ Action effectuée avec succès !", "data": []}

        llm = await ask_llm(msg.question, msg.history)
        t = llm.get("type", "info")

        if t == "query":
            sql = llm.get("sql")
            if not sql:
                return {"type": "info", "answer": llm.get("explication", ""), "data": []}
            data = execute_query(sql)
            return {
                "type": "query",
                "answer": llm.get("explication", ""),
                "data": data,
                "sql": sql,
                "count": len(data)
            }

        elif t == "action":
            return {
                "type": "action_pending",
                "answer": llm.get("explication", ""),
                "confirmation": llm.get("confirmation", "Confirmer cette action ?"),
                "pending_action": {
                    "action": llm.get("action"),
                    "params": llm.get("params", {})
                },
                "data": []
            }

        else:
            return {"type": "info", "answer": llm.get("explication", ""), "data": []}

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Erreur parsing JSON LLM : {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard")
def dashboard():
    stats = {}
    queries = {
        "total_actifs":      "SELECT COUNT(*) as n FROM animaux WHERE statut='actif'",
        "femelles":          "SELECT COUNT(*) as n FROM animaux WHERE statut='actif' AND sexe='F'",
        "males":             "SELECT COUNT(*) as n FROM animaux WHERE statut='actif' AND sexe='M'",
        "en_gestation":      "SELECT COUNT(*) as n FROM reproduction WHERE statut='en_gestation'",
        "alertes_actives":   "SELECT COUNT(*) as n FROM alertes WHERE traitee=FALSE",
        "alertes_critiques": "SELECT COUNT(*) as n FROM alertes WHERE traitee=FALSE AND niveau='critical'",
        "ventes_mois":       "SELECT COUNT(*) as n FROM ventes WHERE MONTH(date_vente)=MONTH(NOW())",
        "ca_mois":           "SELECT COALESCE(SUM(prix_fcfa),0) as n FROM ventes WHERE MONTH(date_vente)=MONTH(NOW())",
    }
    for k, sql in queries.items():
        result = execute_query(sql)
        stats[k] = result[0]["n"] if result else 0
    return stats


@app.get("/api/animaux")
def get_animaux():
    return execute_query("""
        SELECT a.*, r.nom as race,
               fn_age_en_mois(a.id) as age_mois,
               fn_gmq(a.id) as gmq_kg_jour
        FROM animaux a
        LEFT JOIN races r ON a.race_id = r.id
        WHERE a.statut = 'actif'
        ORDER BY a.numero_tag
    """)


@app.get("/api/alertes")
def get_alertes():
    return execute_query("""
        SELECT al.*, a.numero_tag, a.nom as animal_nom
        FROM alertes al
        LEFT JOIN animaux a ON al.animal_id = a.id
        WHERE al.traitee = FALSE
        ORDER BY al.niveau DESC, al.date_creation DESC
        LIMIT 50
    """)


@app.post("/api/alertes/{alert_id}/traiter")
def traiter_alerte(alert_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE alertes SET traitee=TRUE WHERE id=%s", (alert_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True}


@app.get("/api/reproduction/en-cours")
def get_gestations():
    return execute_query("""
        SELECT r.*, a.numero_tag as mere_tag, a.nom as mere_nom,
               p.numero_tag as pere_tag,
               DATEDIFF(r.date_velage_prevue, CURDATE()) as jours_restants
        FROM reproduction r
        JOIN animaux a ON r.mere_id = a.id
        JOIN animaux p ON r.pere_id = p.id
        WHERE r.statut = 'en_gestation'
        ORDER BY r.date_velage_prevue ASC
    """)


@app.get("/health")
def health():
    return {"status": "ok", "app": "BoviBot", "llm": LLM_MODEL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8002, reload=True)


