# Plan d'Implémentation : Middleware Haptique LMU (Python / uv)

## 1. Objectifs du Projet
- Créer un middleware léger permettant de convertir la télémétrie UDP de Le Mans Ultimate (LMU) en retours haptiques stéréophoniques (Gauche/Droite) sur une manette.
- Le projet est prioritairement développé pour Windows, mais doit intégrer une abstraction matérielle stricte pour faciliter un portage futur sous Linux (`evdev`).
- **Gestion des retours haptiques stéréophoniques :**
  - Exploitation conjointe des retours haute fréquence et basse fréquence adaptés pour restituer la télémétrie des deux côtés (Gauche / Droit).
  - **AUCUNE** utilisation des gâchettes vibrantes (Impulse Triggers non supportés par le matériel cible).

---

## 2. Architecture du Projet
Le projet utilisera le gestionnaire de paquets `uv` pour une installation rapide et déterministe.

```text
lmu_haptic_middleware/
├── pyproject.toml           # Configuration uv et dépendances
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py        # Gestion des seuils (JSON)
│   │   └── main.py          # Boucle principale
│   ├── haptics/
│   │   ├── __init__.py
│   │   ├── base.py          # Classe abstraite (Interface)
│   │   ├── windows.py       # Implémentation XInput
│   │   └── linux.py         # Implémentation evdev (Placeholder)
│   ├── telemetry/
│   │   ├── __init__.py
│   │   ├── udp_server.py    # Serveur socket asynchrone ou threadé
│   │   └── lmu_parser.py    # Décodage struct C binaire
│   └── physics/
│       ├── __init__.py
│       └── effects.py       # Logique de conversion Physique -> Vibrations
└── tools/
    └── calibrator.py        # Interface Tkinter pour tester/calibrer
```

---

## 3. Dépendances (à initialiser via uv)
```bash
uv init lmu_haptic_middleware
cd lmu_haptic_middleware
# Utilise les DLLs natives Windows Microsoft GameInput / WGI via ctypes (aucune compilation requise)
```
> **Note :** `Tkinter` fait partie de la bibliothèque standard de Python, pas besoin de l'ajouter.

---

## 4. Instructions pour l'Agent de Code (Sprints)
L'agent devra implémenter le projet en suivant chronologiquement ces 5 phases.

### Phase 1 : La couche d'Abstraction Haptique (`src/haptics/`)
- **Créer `base.py`** : Définir une classe abstraite `HapticController(ABC)`.
  - Méthode requise : `set_vibration(left_intensity: float, right_intensity: float, duration_ms: int = 0)`
  - Les intensités doivent être normalisées entre `0.0` et `1.0`.
- **Créer `windows.py`** : Implémenter `WindowsHapticController` héritant de la base, utilisant `XInput-Python`.
  - Gérer la conversion du float `0.0`-`1.0` vers l'entier `0`-`65535` attendu par XInput.
  - Ne contrôler que `set_vibration` global. Ne pas cibler les gâchettes.
- **Créer `linux.py`** : Implémenter une classe bouchon (`LinuxHapticController`) levant un `NotImplementedError` ou affichant un log (pour le futur portage `evdev`).

### Phase 2 : Le Calibrateur & Moniteur Tkinter (`tools/calibrator.py`)
Développer un script indépendant (utilisant `tkinter` standard) pour tester la manette, configurer les seuils, et monitorer la télémétrie.

**Interface requise (Fenêtre simple) :**
- **Zone Test Moteurs :**
  - Un Slider (Scale) 0.0 à 1.0 pour tester le Moteur Gauche en temps réel.
  - Un Slider (Scale) 0.0 à 1.0 pour tester le Moteur Droit en temps réel.
  - Un bouton "Arrêt d'urgence" (met tout à 0).
- **Zone Configuration des Seuils :**
  - Slider Seuil Blocage Roue (ABS) : Ex 0.15
  - Slider Seuil Patinage (TC) : Ex 0.20
  - Slider Seuil Glissement Latéral : Ex 0.10
  - Bouton Sauvegarder : Exporte les seuils dans un fichier `config.json` à la racine.
- **Zone Moniteur & Télémétrie Temps Réel :**
  - Bouton Start / Stop Server UDP pour lancer le thread d'écoute UDP.
  - Jauges / barres de visualisation en temps réel de la télémétrie reçue et des niveaux de vibration calculés.

> Le calibrateur doit pouvoir instancier le `WindowsHapticController` et exécuter le serveur UDP en tâche de fond (thread) pour le monitoring en temps réel.

### Phase 3 : Le Moteur de Télémétrie (`src/telemetry/`)
- **Créer `lmu_parser.py`** : Utiliser le module `struct` pour décoder le paquet binaire UDP. Focus sur l'extraction des tableaux de 4 floats (AV-G, AV-D, AR-G, AR-D) pour : `mLongitudinalPatchVel`, `mLateralPatchVel`.
- **Créer `udp_server.py`** : Lancer un socket d'écoute sur `127.0.0.1:5606`. Exposer les dernières données reçues via une méthode thread-safe (ou une queue).

### Phase 4 : Le Processeur Physique (`src/physics/effects.py`)
Créer une classe `PhysicsToHaptic` qui prend en entrée le `config.json` et les données décodées, et retourne un tuple `(left_intensity, right_intensity)`.

**Règles de calcul :**
- **Blocage Avant (ABS) :** Si `mLongitudinalPatchVel` (AV-G) > Seuil ABS -> `left_intensity` augmente. Idem pour AV-D -> `right_intensity`.
- **Patinage Arrière (TC) :** Si `mLongitudinalPatchVel` (AR-G) > Seuil TC -> `left_intensity` augmente. Idem pour AR-D -> `right_intensity`.
- **Glissement Latéral :** Si `mLateralPatchVel` (AR) dépasse le seuil, injecter une intensité globale répartie du côté de l'appui.

> **Crucial :** Combiner ces valeurs en utilisant une fonction `max()` pour ne pas dépasser 1.0 par moteur.

### Phase 5 : Le Point d'Entrée (`src/core/main.py`)
Assembler les briques :
1. Charger `config.json`.
2. Détecter l'OS et instancier le bon `HapticController` (`windows.py` par défaut).
3. Démarrer le serveur UDP.
4. Lancer une boucle principale (ex: à 100 Hz / `time.sleep(0.01)`) qui lit la télémétrie, appelle le processeur physique, et envoie les données normalisées au contrôleur haptique.