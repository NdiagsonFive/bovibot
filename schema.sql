-- ============================================================
--  BoviBot — Base de données MySQL + PL/SQL
--  Projet L3 — ESP/UCAD
--  Gestion d'élevage bovin avec assistant IA
-- ============================================================

CREATE DATABASE IF NOT EXISTS bovibot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bovibot;

-- ─── TABLES ──────────────────────────────────────────────────

CREATE TABLE races (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nom VARCHAR(100) NOT NULL,
    origine VARCHAR(100),
    poids_adulte_moyen_kg DECIMAL(6,2),
    production_lait_litre_jour DECIMAL(6,2) DEFAULT 0
);

CREATE TABLE animaux (
    id INT AUTO_INCREMENT PRIMARY KEY,
    numero_tag VARCHAR(30) NOT NULL UNIQUE,
    nom VARCHAR(100),
    race_id INT,
    sexe ENUM('M','F') NOT NULL,
    date_naissance DATE NOT NULL,
    poids_actuel DECIMAL(6,2),
    statut ENUM('actif','vendu','mort','quarantaine') DEFAULT 'actif',
    mere_id INT NULL,
    pere_id INT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (race_id) REFERENCES races(id),
    FOREIGN KEY (mere_id) REFERENCES animaux(id),
    FOREIGN KEY (pere_id) REFERENCES animaux(id)
);

CREATE TABLE pesees (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NOT NULL,
    poids_kg DECIMAL(6,2) NOT NULL,
    date_pesee DATE NOT NULL,
    agent VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

CREATE TABLE sante (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NOT NULL,
    type ENUM('vaccination','traitement','examen','chirurgie') NOT NULL,
    description TEXT NOT NULL,
    date_acte DATE NOT NULL,
    veterinaire VARCHAR(100),
    medicament VARCHAR(200),
    cout DECIMAL(10,2) DEFAULT 0,
    prochain_rdv DATE NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

CREATE TABLE reproduction (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mere_id INT NOT NULL,
    pere_id INT NOT NULL,
    date_saillie DATE NOT NULL,
    date_velage_prevue DATE,
    date_velage_reelle DATE NULL,
    nb_veaux INT DEFAULT 0,
    statut ENUM('en_gestation','vele','avortement','echec') DEFAULT 'en_gestation',
    notes TEXT,
    FOREIGN KEY (mere_id) REFERENCES animaux(id),
    FOREIGN KEY (pere_id) REFERENCES animaux(id)
);

CREATE TABLE alimentation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NOT NULL,
    type_aliment VARCHAR(100) NOT NULL,
    quantite_kg DECIMAL(6,2) NOT NULL,
    date_alimentation DATE NOT NULL,
    cout_unitaire_kg DECIMAL(6,2) DEFAULT 0,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

CREATE TABLE ventes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NOT NULL,
    acheteur VARCHAR(150) NOT NULL,
    telephone_acheteur VARCHAR(20),
    date_vente DATE NOT NULL,
    poids_vente_kg DECIMAL(6,2),
    prix_fcfa DECIMAL(12,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

CREATE TABLE alertes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NULL,
    type ENUM('poids','vaccination','velage','sante','alimentation','autre') NOT NULL,
    message TEXT NOT NULL,
    niveau ENUM('info','warning','critical') DEFAULT 'warning',
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    traitee BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

CREATE TABLE historique_statut (
    id INT AUTO_INCREMENT PRIMARY KEY,
    animal_id INT NOT NULL,
    ancien_statut VARCHAR(20),
    nouveau_statut VARCHAR(20),
    date_changement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (animal_id) REFERENCES animaux(id)
);

-- ─── PROCÉDURES STOCKÉES ──────────────────────────────────────

DELIMITER $$

-- Procédure : enregistrer une pesée + mettre à jour poids_actuel
CREATE PROCEDURE sp_enregistrer_pesee(
    IN p_animal_id INT,
    IN p_poids_kg  DECIMAL(6,2),
    IN p_date      DATE,
    IN p_agent     VARCHAR(100)
)
BEGIN
    DECLARE v_derniere_pesee DECIMAL(6,2);
    DECLARE v_jours INT;
    DECLARE v_gmq   DECIMAL(6,2);

    -- Insérer la pesée
    INSERT INTO pesees (animal_id, poids_kg, date_pesee, agent)
    VALUES (p_animal_id, p_poids_kg, p_date, p_agent);

    -- Mettre à jour le poids actuel de l'animal
    UPDATE animaux SET poids_actuel = p_poids_kg WHERE id = p_animal_id;

    -- Vérifier le GMQ (gain moyen quotidien)
    SELECT poids_kg, DATEDIFF(p_date, date_pesee)
    INTO v_derniere_pesee, v_jours
    FROM pesees
    WHERE animal_id = p_animal_id
      AND date_pesee < p_date
    ORDER BY date_pesee DESC
    LIMIT 1;

    IF v_derniere_pesee IS NOT NULL AND v_jours > 0 THEN
        SET v_gmq = (p_poids_kg - v_derniere_pesee) / v_jours;
        -- Alerte si GMQ < 300g/jour
        IF v_gmq < 0.3 THEN
            INSERT INTO alertes (animal_id, type, message, niveau)
            VALUES (p_animal_id, 'poids',
                CONCAT('GMQ faible : ', ROUND(v_gmq * 1000), ' g/jour (seuil : 300 g/jour)'),
                'warning');
        END IF;
    END IF;
END$$

-- Procédure : déclarer une vente
CREATE PROCEDURE sp_declarer_vente(
    IN p_animal_id   INT,
    IN p_acheteur    VARCHAR(150),
    IN p_telephone   VARCHAR(20),
    IN p_prix        DECIMAL(12,2),
    IN p_poids_vente DECIMAL(6,2),
    IN p_date_vente  DATE
)
BEGIN
    -- Vérifier que l'animal est actif
    DECLARE v_statut VARCHAR(20);
    SELECT statut INTO v_statut FROM animaux WHERE id = p_animal_id;

    IF v_statut != 'actif' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Cet animal ne peut pas être vendu (statut non actif)';
    END IF;

    -- Enregistrer la vente
    INSERT INTO ventes (animal_id, acheteur, telephone_acheteur, date_vente, poids_vente_kg, prix_fcfa)
    VALUES (p_animal_id, p_acheteur, p_telephone, p_date_vente, p_poids_vente, p_prix);

    -- Changer le statut de l'animal
    UPDATE animaux SET statut = 'vendu' WHERE id = p_animal_id;
END$$

-- ─── FONCTIONS ────────────────────────────────────────────────

-- Fonction : âge en mois
CREATE FUNCTION fn_age_en_mois(p_animal_id INT)
RETURNS INT
READS SQL DATA
BEGIN
    DECLARE v_date_naissance DATE;
    SELECT date_naissance INTO v_date_naissance FROM animaux WHERE id = p_animal_id;
    RETURN TIMESTAMPDIFF(MONTH, v_date_naissance, CURDATE());
END$$

-- Fonction : gain moyen quotidien (GMQ) sur toutes les pesées
CREATE FUNCTION fn_gmq(p_animal_id INT)
RETURNS DECIMAL(6,3)
READS SQL DATA
BEGIN
    DECLARE v_premiere_pesee DECIMAL(6,2);
    DECLARE v_derniere_pesee DECIMAL(6,2);
    DECLARE v_premiere_date  DATE;
    DECLARE v_derniere_date  DATE;
    DECLARE v_jours INT;

    SELECT poids_kg, date_pesee INTO v_premiere_pesee, v_premiere_date
    FROM pesees WHERE animal_id = p_animal_id ORDER BY date_pesee ASC LIMIT 1;

    SELECT poids_kg, date_pesee INTO v_derniere_pesee, v_derniere_date
    FROM pesees WHERE animal_id = p_animal_id ORDER BY date_pesee DESC LIMIT 1;

    SET v_jours = DATEDIFF(v_derniere_date, v_premiere_date);

    IF v_jours = 0 OR v_premiere_pesee IS NULL THEN
        RETURN 0;
    END IF;

    RETURN (v_derniere_pesee - v_premiere_pesee) / v_jours;
END$$

-- ─── TRIGGERS ─────────────────────────────────────────────────

-- Trigger : log changement de statut
CREATE TRIGGER trg_historique_statut
BEFORE UPDATE ON animaux
FOR EACH ROW
BEGIN
    IF OLD.statut != NEW.statut THEN
        INSERT INTO historique_statut (animal_id, ancien_statut, nouveau_statut)
        VALUES (OLD.id, OLD.statut, NEW.statut);
    END IF;
END$$

-- Trigger : alerte vaccination dépassée
CREATE TRIGGER trg_alerte_vaccination
AFTER INSERT ON sante
FOR EACH ROW
BEGIN
    IF NEW.prochain_rdv IS NOT NULL AND NEW.prochain_rdv < CURDATE() THEN
        INSERT INTO alertes (animal_id, type, message, niveau)
        VALUES (NEW.animal_id, 'vaccination',
            CONCAT('Rappel vaccination en retard depuis le ', NEW.prochain_rdv),
            'critical');
    END IF;
END$$

-- Trigger : alerte poids faible à l'insertion de pesée (complémentaire à la procédure)
CREATE TRIGGER trg_alerte_poids_faible
AFTER INSERT ON pesees
FOR EACH ROW
BEGIN
    DECLARE v_age_mois INT;
    SELECT fn_age_en_mois(NEW.animal_id) INTO v_age_mois;
    -- Bovin de moins de 6 mois : poids < 60 kg = alerte
    IF v_age_mois <= 6 AND NEW.poids_kg < 60 THEN
        INSERT INTO alertes (animal_id, type, message, niveau)
        VALUES (NEW.animal_id, 'poids',
            CONCAT('Poids critique pour un veau de ', v_age_mois, ' mois : ', NEW.poids_kg, ' kg'),
            'critical');
    END IF;
END$$

DELIMITER ;

-- ─── EVENTS (MySQL Event Scheduler) ──────────────────────────

SET GLOBAL event_scheduler = ON;

DELIMITER $$

-- Event quotidien : alertes vêlages dans les 7 prochains jours
CREATE EVENT evt_alerte_velages
ON SCHEDULE EVERY 1 DAY
STARTS CURRENT_TIMESTAMP
DO
BEGIN
    INSERT INTO alertes (animal_id, type, message, niveau)
    SELECT r.mere_id, 'velage',
        CONCAT('Vêlage prévu dans ', DATEDIFF(r.date_velage_prevue, CURDATE()), ' jour(s) : ', a.numero_tag),
        'info'
    FROM reproduction r
    JOIN animaux a ON r.mere_id = a.id
    WHERE r.statut = 'en_gestation'
      AND r.date_velage_prevue BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
      AND NOT EXISTS (
          SELECT 1 FROM alertes al
          WHERE al.animal_id = r.mere_id
            AND al.type = 'velage'
            AND DATE(al.date_creation) = CURDATE()
      );
END$$

-- Event hebdomadaire : rapport croissance (insère une alerte globale résumée)
CREATE EVENT evt_rapport_croissance
ON SCHEDULE EVERY 1 WEEK
STARTS CURRENT_TIMESTAMP
DO
BEGIN
    DECLARE v_nb_animaux INT;
    DECLARE v_gmq_moyen  DECIMAL(6,3);

    SELECT COUNT(*) INTO v_nb_animaux FROM animaux WHERE statut = 'actif';

    INSERT INTO alertes (animal_id, type, message, niveau)
    VALUES (NULL, 'autre',
        CONCAT('Rapport hebdo : ', v_nb_animaux, ' animaux actifs. Consultez le tableau de bord pour les détails.'),
        'info');
END$$

DELIMITER ;

-- ─── DONNÉES DE TEST ──────────────────────────────────────────

INSERT INTO races (nom, origine, poids_adulte_moyen_kg, production_lait_litre_jour) VALUES
('Zébu Gobra',   'Sénégal',   350.00, 3.5),
('Ndama',        'Guinée',    250.00, 2.0),
('Holstein',     'Europe',    650.00, 25.0),
('Jersiaise',    'Jersey',    400.00, 20.0);

INSERT INTO animaux (numero_tag, nom, race_id, sexe, date_naissance, poids_actuel, statut) VALUES
('TAG-001', 'Baaba',  1, 'M', '2021-03-10', 320.00, 'actif'),
('TAG-002', 'Yaye',   1, 'F', '2020-06-15', 280.00, 'actif'),
('TAG-003', 'Samba',  2, 'M', '2022-01-20', 200.00, 'actif'),
('TAG-004', 'Fatou',  2, 'F', '2021-09-05', 195.00, 'actif'),
('TAG-005', 'Lait',   3, 'F', '2019-11-12', 580.00, 'actif'),
('TAG-006', 'Veau1',  1, 'M', '2025-11-01', 85.00,  'actif'),
('TAG-007', 'Veau2',  1, 'F', '2025-12-15', 72.00,  'actif');

-- Mise à jour parenté
UPDATE animaux SET mere_id = 2, pere_id = 1 WHERE numero_tag IN ('TAG-006','TAG-007');

INSERT INTO pesees (animal_id, poids_kg, date_pesee, agent) VALUES
(1, 290.00, '2026-01-01', 'Ousmane Diallo'),
(1, 305.00, '2026-02-01', 'Ousmane Diallo'),
(1, 320.00, '2026-03-01', 'Ousmane Diallo'),
(2, 255.00, '2026-01-01', 'Ousmane Diallo'),
(2, 268.00, '2026-02-01', 'Ousmane Diallo'),
(2, 280.00, '2026-03-01', 'Ousmane Diallo'),
(6, 45.00,  '2025-11-01', 'Ousmane Diallo'),
(6, 62.00,  '2025-12-01', 'Ousmane Diallo'),
(6, 85.00,  '2026-01-15', 'Ousmane Diallo');

INSERT INTO sante (animal_id, type, description, date_acte, veterinaire, medicament, cout, prochain_rdv) VALUES
(1, 'vaccination', 'Vaccin FMDV (fièvre aphteuse)', '2026-01-10', 'Dr Ndiaye', 'FMDV Vac', 15000, '2026-07-10'),
(2, 'vaccination', 'Vaccin FMDV', '2026-01-10', 'Dr Ndiaye', 'FMDV Vac', 15000, '2026-07-10'),
(3, 'traitement',  'Traitement parasites internes', '2026-02-05', 'Dr Ndiaye', 'Ivermectine', 8000, NULL),
(5, 'examen',      'Contrôle production laitière', '2026-03-01', 'Dr Ndiaye', NULL, 5000, '2026-06-01');

INSERT INTO reproduction (mere_id, pere_id, date_saillie, date_velage_prevue, date_velage_reelle, nb_veaux, statut) VALUES
(2, 1, '2025-08-01', '2026-05-10', NULL, 0, 'en_gestation'),
(4, 3, '2025-09-15', '2026-06-24', NULL, 0, 'en_gestation');

INSERT INTO alimentation (animal_id, type_aliment, quantite_kg, date_alimentation, cout_unitaire_kg) VALUES
(1, 'Foin', 8.0, '2026-03-01', 150),
(2, 'Foin', 7.0, '2026-03-01', 150),
(5, 'Concentre', 5.0, '2026-03-01', 350),
(6, 'Lait maternel', 3.0, '2026-03-01', 0);
