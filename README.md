# BoviBot — Projet L3 ESP/UCAD

## Démarrage rapide

1. Créer la base et activer l'event scheduler :
   mysql -u root -p < schema.sql

2. Configurer l'environnement :
   cp .env.example .env # Éditer avec vos valeurs

3. Installer les dépendances :
   pip install -r requirements.txt

4. Lancer le backend :
   python app.py # port 8002

5. Ouvrir index.html (mettre l'URL backend dans la variable API)

## PL/SQL inclus

- Procédures : sp_enregistrer_pesee, sp_declarer_vente
- Fonctions : fn_age_en_mois, fn_gmq
- Triggers : trg_historique_statut, trg_alerte_vaccination, trg_alerte_poids_faible
- Events : evt_alerte_velages (quotidien), evt_rapport_croissance (hebdo)

## Livrables

- Lien plateforme déployée + lien chat IA
- Rapport PDF (MCD, MLD, PL/SQL documenté)
- Présentation PowerPoint
