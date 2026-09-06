Voici l'analyse comparative détaillée entre CompactScoring et FullScoringSession (avec le VehicleScoring du joueur), suivie de la structure du nouveau modèle de données unifié.
  ──────
  ### 1. Tableau comparatif exhaustif : CompactScoring vs FullScoring

   Champ                    | Type     | Présent dans CompactScoring (10 Hz) |    Présent dans FullScoringSession (2–5 Hz)    | Signification & Unité                                  | Différence / Piège sémantique
  --------------------------|----------|-------------------------------------|------------------------------------------------|--------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------
   track_name               | str      |            ✅ track_name            |                 ✅ track_name                  | Nom du circuit                                         | Identique.
   session                  | int      |             ✅ session              |                   ✅ session                   | Type de session (0=Test, 1-4=FP, 5-8=Qual, 10-13=Race) | Identique.
   current_et               | float    |            ✅ current_et            |                 ✅ current_et                  | Elapsed Time session (secondes)                        | Identique (précision UDP).
   max_laps                 | int      |             ✅ max_laps             |                  ✅ max_laps                   | Nombre de tours max session                            | Identique.
   in_realtime              | bool     |           ✅ in_realtime            |                 ✅ in_realtime                 | Vrai si le jeu n'est pas en pause/replay               | Identique.
   lap_dist (Session)       | float    |             ✅ lap_dist             |                  ✅ lap_dist                   | Longueur totale du tour (mètres)                       | ⚠️ PIÈGE MAJEUR : Dans Compact, lap_dist est la longueur du circuit. Dans Full.player_vehicle, lap_dist est la position du
                            |          |                                     |                                                |                                                        | véhicule sur la spline !
   total_laps               | int      |            ✅ total_laps            |          ✅ player_vehicle.total_laps          | Tours complétés par le joueur                          | Identique.
   sector                   | int      |              ✅ sector              |            ✅ player_vehicle.sector            | Secteur actuel (0=S3, 1=S1, 2=S2)                      | Protocole brut isiMotor : 0 = Secteur 3.
   in_garage_stall          | bool     |         ✅ in_garage_stall          |       ✅ player_vehicle.in_garage_stall        | Dans le box des stands                                 | Identique.
   count_lap_flag           | int      |          ✅ count_lap_flag          |        ✅ player_vehicle.count_lap_flag        | Validité du tour (0=invalide, 1=cut, 2=valide)         | Identique.
   cur_sector1              | float    |           ✅ cur_sector1            |         ✅ player_vehicle.cur_sector1          | Temps S1 tour en cours (s)                             | 0.0 tant que S1 n'est pas franchi.
   cur_sector2              | float    |           ✅ cur_sector2            |         ✅ player_vehicle.cur_sector2          | Temps cumulé S1+S2 en cours (s)                        | 0.0 tant que S2 n'est pas franchi.
   last_sector1             | float    |           ✅ last_sector1           |         ✅ player_vehicle.last_sector1         | Temps S1 du tour précédent (s)                         | Identique.
   last_sector2             | float    |           ✅ last_sector2           |         ✅ player_vehicle.last_sector2         | Temps cumulé S1+S2 tour précédent                      | Identique.
   last_lap_time            | float    |          ✅ last_lap_time           |        ✅ player_vehicle.last_lap_time         | Temps total du dernier tour (s)                        | Identique.
   best_sector1             | float    |           ✅ best_sector1           |         ✅ player_vehicle.best_sector1         | Meilleur S1 personnel (s)                              | Identique.
   best_sector2             | float    |           ✅ best_sector2           |         ✅ player_vehicle.best_sector2         | Meilleur S1+S2 cumulé (s)                              | Identique.
   best_lap_time            | float    |          ✅ best_lap_time           |        ✅ player_vehicle.best_lap_time         | Meilleur tour personnel (s)                            | Identique.
   cur_sector2_indiv        | float    |              ✅ (prop)              |                   ✅ (prop)                    | S2 isolé = cur_s2 - cur_s1                             | Calculé à la volée.
   last_sector2_indiv       | float    |              ✅ (prop)              |                   ✅ (prop)                    | S2 isolé dernier tour                                  | Calculé à la volée.
   last_sector3_indiv       | float    |              ✅ (prop)              |                   ✅ (prop)                    | S3 isolé dernier tour (last_lap - last_s2)             | Calculé à la volée.
   best_sector2_indiv       | float    |              ✅ (prop)              |                   ✅ (prop)                    | S2 isolé du best lap                                   | Calculé à la volée.
   ---                      | ---      |                 ---                 |                      ---                       | ---                                                    | ---
   car_lap_dist (Joueur)    | float    |              ❌ Absent              |           ✅ player_vehicle.lap_dist           | Distance de la voiture sur le tour (m)                 | ⚠️ Absent de Compact. C'est TelemInfo ou DeltaEngine qui doit le fournir à 100 Hz.
   lap_start_et             | float    |              ❌ Absent              |         ✅ player_vehicle.lap_start_et         | Heure ET début du tour en cours                        | Absent de Compact.
   time_into_lap            | float    |              ❌ Absent              |        ✅ player_vehicle.time_into_lap         | Temps écoulé dans le tour actuel                       | ⚠️ Cause du clignotement delta (valait 0 dans Compact).
   estimated_lap_time       | float    |              ❌ Absent              |      ✅ player_vehicle.estimated_lap_time      | Estimation isiMotor du temps au tour                   | Absent de Compact.
   driver_name              | str      |              ❌ Absent              |         ✅ player_vehicle.driver_name          | Nom du pilote local                                    | Absent de Compact.
   vehicle_name             | str      |              ❌ Absent              |         ✅ player_vehicle.vehicle_name         | Nom de la voiture / livrée                             | Absent de Compact.
   vehicle_class            | str      |              ❌ Absent              |        ✅ player_vehicle.vehicle_class         | Classe ("Hypercar", "GT3"...)                          | Absent de Compact.
   place / qualification    | int      |              ❌ Absent              |            ✅ player_vehicle.place             | Position au général / qualif                           | Absent de Compact.
   finish_status            | int      |              ❌ Absent              |        ✅ player_vehicle.finish_status         | 0=Running, 1=Finished, 2=DNF, 3=DQ                     | Absent de Compact.
   num_penalties            | int      |              ❌ Absent              |        ✅ player_vehicle.num_penalties         | Nombre de pénalités actives                            | Absent de Compact.
   track_limits_steps       | int      |              ❌ Absent              |    ✅ player_vehicle.lmu.track_limits_steps    | Avertissements track limits LMU                        | Absent de Compact.
   in_pits / pit_state      | bool/int |              ❌ Absent              |           ✅ player_vehicle.in_pits            | État dans la pitlane / arrêt                           | Absent de Compact.
   num_pitstops             | int      |              ❌ Absent              |         ✅ player_vehicle.num_pitstops         | Nombre d'arrêts effectués                              | Absent de Compact.
   time_behind_leader       | float    |              ❌ Absent              |      ✅ player_vehicle.time_behind_leader      | Écart au leader (secondes)                             | Absent de Compact.
   time_behind_next         | float    |              ❌ Absent              |       ✅ player_vehicle.time_behind_next       | Écart à la voiture précédente                          | Absent de Compact.
   laps_behind_*            | int      |              ❌ Absent              |        ✅ player_vehicle.laps_behind_*         | Retard en tours                                        | Absent de Compact.
   pos / vel / accel        | Vector3  |              ❌ Absent              |            ✅ player_vehicle.pos...            | Position & vecteurs spatiaux                           | Absent de Compact.
   Conditions Piste & Météo | float    |              ❌ Absent              | ✅ ambient_temp, track_temp, raining, wetness  | Données météo session                                  | Absent de Compact.
   Grille / Véhicules       | list     |              ❌ Absent              |           ✅ vehicles (30+ voitures)           | Tous les adversaires                                   | Absent de Compact.
   Drapeaux globaux / FCY   | int      |              ❌ Absent              | ✅ game_phase, yellow_flag_state, sector_flags | Drapeaux de course                                     | Absent de Compact.

### 2. Le Nouveau Modèle de Données Proposé

  Pour éliminer définitivement les conflits et les crashs dans les moteurs, le modèle est scindé en deux :

  #### Classe 1 : BaseTimingState (Données Communes)

  Alimentée en continu à 10 Hz par CompactScoring (ou à 2–5 Hz par FullScoringSession en fallback).
  C'est la source unique pour le timing, les secteurs, le delta et le HUD.

    @dataclass
    class BaseTimingState:
        """Données communes de session et timing joueur garanties à 10Hz."""
        # Session
        track_name: str = ""
        session: int = 0
        current_et: float = 0.0
        track_length: float = 0.0        # Renommé pour lever l'ambiguïté avec la distance de la voiture
        max_laps: int = 0
        in_realtime: bool = True
        
        # Joueur - État Tour & Secteur
        total_laps: int = 0
        sector: int = 1                  # Normalisé 1, 2, 3 (fini le 0 pour S3)
        in_garage: bool = False
        count_lap_flag: int = 2          # 0=invalide, 1=cut, 2=valide
        is_lap_valid: bool = True
        
        # Joueur - Temps de Secteurs (Cumulés et Isolés)
        cur_sector1: float = 0.0
        cur_sector2: float = 0.0         # Cumulé (S1+S2)
        cur_sector2_indiv: float = 0.0   # S2 isolé
        
        last_sector1: float = 0.0
        last_sector2: float = 0.0
        last_sector2_indiv: float = 0.0
        last_sector3_indiv: float = 0.0
        last_lap_time: float = 0.0
        
        best_sector1: float = 0.0
        best_sector2: float = 0.0
        best_sector2_indiv: float = 0.0
        best_lap_time: float = 0.0

#### Classe 2 : FullGridScoringState (Données Exclusives FullScoring)

  Hérite de BaseTimingState (ou l'englobe) et ajoute tout ce qui requiert la grille ou les détails avancés (2–5 Hz) :

    @dataclass
    class FullGridScoringState(BaseTimingState):
        """Données riches multi-véhicules, classement, pénalités et environnement."""
        # Session Avancée & Environnement
        end_et: float = 0.0
        game_phase: int = 5
        is_fcy: bool = False
        yellow_flag_state: int = 0
        sector_flags: tuple[int, int, int] = (0, 0, 0)
        start_light: int = 0
        ambient_temp: float = 0.0
        track_temp: float = 0.0
        raining: float = 0.0
        avg_path_wetness: float = 0.0
        
        # Joueur - Détails Course & Stand
        driver_name: str = ""
        vehicle_name: str = ""
        vehicle_class: str = ""
        place: int = 1
        qualification: int = 0
        finish_status: int = 0
        num_pitstops: int = 0
        num_penalties: int = 0
        track_limits_steps: int = 0
        in_pits: bool = False
        pit_state: int = 0
        time_behind_leader: float = 0.0
        time_behind_next: float = 0.0
        laps_behind_leader: int = 0
        laps_behind_next: int = 0
        
        # Joueur - Métriques tour (Full-only)
        lap_start_et: float = 0.0
        time_into_lap: float = 0.0
        car_lap_dist: float = 0.0        # Position de la voiture sur le tour (m)
        
        # Grille complète
        num_vehicles: int = 0
        leaderboard: list[VehicleScoring] = field(default_factory=list)
        vehicles: list[VehicleScoring] = field(default_factory=list)
  ──────
  ### 3. Conséquence directe pour les Engines

  1. DeltaEngine & CockpitHUD :
      • Consomment uniquement state.timing (BaseTimingState) ou les propriétés exposées par TelemetryStateStore.
      • Interdiction absolue d'écouter ou manipuler directement les paquets bruts UDP CompactScoring ou FullScoringSession.
      • La distance du joueur car_lap_dist provient de state.lap_dist (fourni à 100 Hz par l'odométrie Delta ou TelemInfo), sans jamais être écrasée par track_length.
  2. RaceEngineer (Traffic, Spotter, PitCrew) :
      • Les sous-rôles de trafic/grille consomment state.grid (FullGridScoringState).
      • Le rôle PaceNotes consomme state.lap_dist et state.timing.total_laps.


  Si ce tableau et cette séparation te conviennent, je peux implémenter ce modèle dans state_store.py et stabiliser le calcul des temps de secteurs dans delta_engine.py.
