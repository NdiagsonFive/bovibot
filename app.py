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
from pydantic import BaseModel
from fastapi import HTTPException
load_dotenv()

app = FastAPI(title="BoviBot API", version="1.0.0")
@app.get("/setup-db")
def setup_db():
    import mysql.connector
    import os
    try:
        # On force la connexion en tant que 'root' pour avoir les droits de création
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user="root",  # Ne pas changer, c'est pour l'admin
            password=os.getenv("DB_PASSWORD"), # Il faut que ce soit le mot de passe root actuel !
            port=int(os.getenv("DB_PORT", 3306))
        )
        cursor = conn.cursor()
        
        # Création du nouvel utilisateur
        cursor.execute("CREATE USER IF NOT EXISTS 'bovibot_user'@'%' IDENTIFIED BY 'BoviPass123!';")
        cursor.execute("GRANT ALL PRIVILEGES ON *.* TO 'bovibot_user'@'%';")
        cursor.execute("FLUSH PRIVILEGES;")
        
        return {"status": "success", "message": "✅ Utilisateur 'bovibot_user' créé avec le mot de passe 'BoviPass123!' !"}
    
    except Exception as e:
        return {"status": "error", "message": f"Erreur : {str(e)}"}
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,  # ← False obligatoire avec allow_origins=["*"]
)

# ── Configuration ───────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "bovibot"),
}
# Configuration API
LLM_API_KEY = os.getenv("OPENAI_API_KEY") # On utilise la variable définie sur Railway
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_BASE_URL = "https://api.groq.com/openai/v1"

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

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    # Récupération sécurisée de la clé
    api_key = os.getenv("OPENAI_API_KEY")
    
    try:
        # 1. GESTION DES ACTIONS (Si confirmation reçue)
        if msg.confirm_action and msg.pending_action:
            try:
                # Appelle ta procédure de base de données
                call_procedure(msg.pending_action["action"], msg.pending_action["params"])
                return {"type": "action_done", "answer": "✅ L'opération a été enregistrée dans la base de données.", "data": []}
            except Exception as e:
                return {"type": "error", "answer": f"Erreur base de données : {str(e)}", "data": []}

        # 2. APPEL IA (Méthode directe via httpx pour éviter les erreurs de modules)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "Tu es BoviBot. Réponds TOUJOURS en JSON avec les clés 'type' (info/query/action), 'explication' et 'sql' (si besoin)."},
                        {"role": "user", "content": msg.question}
                    ],
                    "response_format": {"type": "json_object"}
                },
                timeout=25.0
            )
        
        if response.status_code != 200:
            return {"type": "info", "answer": "L'IA est momentanément indisponible.", "data": []}

        llm_content = response.json()['choices'][0]['message']['content']
        llm = json.loads(llm_content)
        
        # 3. LOGIQUE SQL
        t = llm.get("type", "info")
        if t == "query":
            sql = llm.get("sql")
            try:
                # On tente l'exécution mais on ne plante pas si la DB refuse (Access Denied)
                data = execute_query(sql) if sql else []
                return {
                    "type": "query",
                    "answer": llm.get("explication", "Voici les données :"),
                    "data": data,
                    "sql": sql,
                    "count": len(data)
                }
            except Exception as db_err:
                # On informe l'utilisateur sans faire d'erreur 500
                return {"type": "info", "answer": f"L'IA a généré une requête, mais la base de données a répondu : {str(db_err)}", "data": []}

        # Réponse info classique
        return {"type": "info", "answer": llm.get("explication", "Je ne peux pas répondre précisément."), "data": []}

    except Exception as e:
        # Capture toutes les erreurs pour éviter le crash ASCII que tu as vu
        return {"type": "error", "answer": f"Désolé, une erreur technique est survenue.", "data": []}
