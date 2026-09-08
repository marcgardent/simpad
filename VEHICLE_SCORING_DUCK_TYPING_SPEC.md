# Dette technique — duck typing `isinstance`/`getattr` dans le pipeline scoring

## Contexte

En construisant `WallOfFameEngine` ([TIME_STATUS_SPEC.md](TIME_STATUS_SPEC.md)), le paddock-scan copié depuis `DeltaEngine._apply_scoring_update` a reproduit tel quel un anti-pattern que `scripts/lint_oop_evil.py` interdit explicitement (mémo `review.md`, section "cripy code") :

```python
def _veh_bests(v) -> tuple[float, float, float]:
    if isinstance(v, dict):
        return (float(v.get("mBestSector1", ...)), ...)
    return (float(getattr(v, "best_sector1", 0.0) or 0.0), ...)
```

Règle du linter : `getattr()`/`hasattr()`/`setattr()` interdits sans ambiguïté ; `isinstance()` acceptable **uniquement dans une Factory** (nom de fichier/classe/méthode contenant `factory`/`create_`/`build_`/`make_`) — ailleurs on type et on utilise le polymorphisme.

**Déjà corrigé** dans `simpulse/core/telemetry/wall_of_fame_engine.py` : `VehicleBests` (`@dataclass(frozen=True)`, champs `is_player`/`best_sector1`/`best_sector2`/`best_lap_time`) + `VehicleBests.build(vehicle)` (classmethod nommée `build_...` → exemptée par le linter), seul endroit qui branche sur `dict` vs `isimotor_rawudp_client.VehicleScoring`. Le reste du moteur ne lit plus que des attributs typés.

Ce doc catalogue les endroits où le **même** anti-pattern (ou une variante voisine : dispatch `isinstance` sur plusieurs formats bruts, `getattr` défensif sur un type qui n'en a pas besoin) subsiste ailleurs dans le pipeline scoring, avec un plan de consolidation autour de `VehicleBests` et d'une nouvelle Factory de parsing.

Portée volontairement limitée au pipeline scoring (`delta_engine.py`, `sector_engine.py`) — pas un audit exhaustif du linter sur tout le repo (`python scripts/lint_oop_evil.py simpulse -s` remonte 1560 problèmes sur 84 fichiers, très majoritairement "State mutation outside `__init__`"/"Law of Demeter", un style déjà assumé pour les classes moteur type `SectorEngine`/`DeltaEngine` — hors sujet ici).

## Inventaire

### 1. `SectorEngine.update_session_bests._veh_bests` — doublon exact, priorité haute

`simpulse/core/telemetry/sector_engine.py:191-202` :

```python
def _veh_bests(v):
    if isinstance(v, dict):
        return (float(v.get("mBestSector1", v.get("bestSector1", 0.0))), ...)
    return (float(getattr(v, "best_sector1", 0.0) or 0.0), ...)
```

Fonction interne à `update_session_bests()`, structurellement identique à celle déjà remplacée dans `WallOfFameEngine`. **Fix : supprimer, remplacer les 3 lignes d'appel par `VehicleBests.build(v)`** (déplacer `VehicleBests` dans un module neutre si on veut éviter que `sector_engine.py` dépende de `wall_of_fame_engine.py` — voir "Points ouverts").

### 2. `DeltaEngine._apply_scoring_update`'s paddock scan — doublon exact, déjà partiellement redondant

`simpulse/core/telemetry/delta_engine.py:994-1016` : `_is_player()` + le `isinstance(v, dict)` inline dans la boucle — **exactement** la logique que `WallOfFameEngine.update_from_scoring()` recalcule déjà juste au-dessus (ligne 990 : `self._wall_of_fame.update_from_scoring(best_lap, vehicles_src)`). Ce bloc ne sert plus qu'à alimenter `self._paddock_best_lap`/`_paddock_cum_s1`/`_paddock_cum_s2` (les champs *legacy*, cf. [TIME_STATUS_SPEC.md](TIME_STATUS_SPEC.md) étape 1) — une fois l'étape 4 de la migration TimeStatus faite (suppression des champs dépréciés), **ce bloc entier disparaît**, pas seulement son duck typing.
**Fix immédiat (avant la suppression) : remplacer `_is_player(v)`/le duck typing inline par `VehicleBests.build(v)`**, cohérent avec le reste et sans attendre l'étape 4.

### 3. `_individual_sector_splits(profile)` — faux positif, pas du vrai duck typing

`simpulse/core/telemetry/delta_engine.py:102-127` :

```python
s1c = float(getattr(profile, "sector_1_time", 0.0) or 0.0)
s2c = float(getattr(profile, "sector_2_time", 0.0) or 0.0)
lap = float(getattr(profile, "lap_time", 0.0) or 0.0)
```

`profile` est toujours `Optional[ReferenceLapProfile]` — jamais un dict, jamais une autre forme. Le `None` est déjà géré juste au-dessus (`if profile is None: return 0.0, 0.0, 0.0`). Le `getattr` ici ne protège contre rien de réel : c'est de la prudence défensive sur un type qui n'en a pas besoin (même correctif déjà appliqué à `WallOfFameEngine.load_all_time_from_disk`/`_decompose`).
**Fix : accès direct** `profile.sector_1_time` / `profile.sector_2_time` / `profile.lap_time`. Le plus simple des quatre chantiers — aucun risque, aucune Factory à créer.

### 4. `DeltaEngine._find_player_vehicle` — duck typing dict, isolable dans la Factory de parsing

`simpulse/core/telemetry/delta_engine.py:544-554` :

```python
def _find_player_vehicle(self, vehicles: list) -> Optional[dict]:
    if not isinstance(vehicles, list):
        return None
    for v in vehicles:
        if isinstance(v, dict) and (v.get("mIsPlayer") or v.get("isPlayer")):
            return v
    ...
```

Seul appelant : la branche `dict` de `update_scoring()` (item 5 ci-dessous) — `vehicles` y est déjà garanti être une liste de dicts JSON à ce point (extraite de `scoring_info.get("mVehicles", ...)`). Le `isinstance()` par élément est donc de la prudence sur un contrat déjà garanti par l'appelant, pas un vrai dispatch polymorphe.
**Fix : à absorber dans la future Factory de parsing scoring (item 5)** plutôt que corrigé isolément — cette méthode disparaît quand la Factory prend le dict `mScoringInfo` en entrée et retourne directement le véhicule joueur typé.

### 5. `DeltaEngine.update_scoring` — le vrai morceau : dispatch 3 formats bruts, candidat Factory

`simpulse/core/telemetry/delta_engine.py:769-863`, ~95 lignes, 5 `isinstance(scoring_js, ...)` (`FullScoringSession` / `CompactScoring` / `dict`, deux fois pour extraire `vehicles_src`). Contrairement aux items 1-2, **ce n'est pas un doublon à supprimer** : c'est un point d'entrée public toujours actif, exercé par une quarantaine de tests (`test_delta_engine.py`, `test_sector_view_stability.py`, `test_sector_times_freeze.py`, ...) avec les 3 formats réels — dict JSON legacy, `CompactScoring`, `FullScoringSession`. `TelemetryBus.process_raw_packet` documente déjà que la branche `dict` est "Defensive-only ... never reaches the Store via CHANNEL_ROUTING ... kept for callers that still hand-build a JSON-shaped scoring dict directly" (`telemetry_bus.py:268-273`) — les deux autres branches, elles, restent le chemin de test direct de `DeltaEngine` sans passer par `TelemetryStateStore`.

C'est exactement le cas d'usage que le linter réserve à une Factory : isoler le branchement sur la forme brute dans **une seule** classe/fonction nommée en conséquence, qui construit un objet typé unique (mêmes champs que ceux déjà extraits manuellement aux lignes 776-853 : `track_name`, `track_len`, `veh_name`, `laps_comp`, `cur_s1`, `best_lap`, ...) — `_apply_scoring_update` ne recevrait plus que cet objet, plus aucun `isinstance` dans le corps métier.

**Fix proposé** : `ScoringSnapshotFactory.build(scoring_js) -> ScoringSnapshot` (nom de classe contenant `Factory` → toute la logique `isinstance` interne est couverte par l'exemption du linter), `ScoringSnapshot` étant un `@dataclass(frozen=True)` reprenant les ~18 champs actuellement dispersés en variables locales. `update_scoring()` devient `self._apply_scoring_update(**dataclasses.asdict(ScoringSnapshotFactory.build(scoring_js)), vehicles_src=...)`.
Risque plus élevé que 1-3 (grosse méthode, forte couverture de tests existants à ne pas casser) — voir plan de migration.

### 6. `DeltaEngine.update_physics(veh_speed_ms: Union[float, TelemInfo], ...)` — variante : overload déguisé en `isinstance`

`simpulse/core/telemetry/delta_engine.py:1110-1144` :

```python
if isinstance(veh_speed_ms, TelemInfo):
    telem = veh_speed_ms
    veh_speed_ms = float(telem.speed_mps)
    throttle = float(telem.unfiltered_throttle)
    ...
```

Différent des items 1-5 (pas du parsing JSON) mais même racine : une méthode qui accepte deux formes d'entrée incompatibles et les distingue par `isinstance`. C'est aussi trait pour trait le pattern que le mémo interdit séparément ("Option en argument : soit suppression de l'appel quand la data n'est pas dispo, soit tu découpes en deux méthodes"). `update_physics_from_view()` (ligne ~333 de `reference_lap.py`) fait déjà exactement ce découpage un niveau au-dessus (extrait les scalaires de `TelemInfo` puis appelle `update_physics(veh_speed_ms=..., throttle=..., ...)`) — l'`isinstance` dans `DeltaEngine.update_physics` lui-même est donc redondant avec un appelant qui existe déjà.
**Fix : supprimer la branche `isinstance(veh_speed_ms, TelemInfo)`**, garder uniquement la signature scalaire ; tout appelant qui a un `TelemInfo` sous la main passe par `update_physics_from_view()` (ou fait l'extraction lui-même, 8 lignes). Vérifier d'abord qui appelle `update_physics(telem_info_object)` directement (grep ciblé avant de couper).

## Plan de migration

Par ordre de risque croissant, chaque étape testée et committée séparément (même principe que [TIME_STATUS_SPEC.md](TIME_STATUS_SPEC.md) : pas de big-bang) :

1. **Item 3** (`_individual_sector_splits` — accès direct). Zéro risque, zéro test à toucher.
2. **Déplacer `VehicleBests`** de `wall_of_fame_engine.py` vers un module neutre sans dépendance descendante — proposition : `simpulse/core/telemetry/scoring_vehicle.py` (ou `simpulse_sdk/models/scoring.py`, déjà le foyer de `BaseTimingState`/`FullGridScoringState` — cohérent side SDK plutôt que Core). `wall_of_fame_engine.py` et `sector_engine.py` importent tous les deux depuis là.
3. **Item 1** (`SectorEngine._veh_bests` → `VehicleBests.build`). Un seul appelant, couvert par `tests/test_sector_colors.py`/`test_expected_status.py::TestSectorVioletVsPaddock`.
4. **Item 2** (`DeltaEngine`'s paddock-scan duck typing → `VehicleBests.build`), en gardant le comportement identique (ce bloc légitime lui-même disparaîtra à l'étape 4 de [TIME_STATUS_SPEC.md](TIME_STATUS_SPEC.md), pas avant).
5. **Item 6** (`update_physics` overload) — grep les appelants de `update_physics(` avec un `TelemInfo` en premier argument positionnel avant de couper la branche.
6. **Item 4 + 5** (`_find_player_vehicle` + `update_scoring`'s dispatch → `ScoringSnapshotFactory`) — le plus gros morceau, à faire en dernier, avec un test de non-régression qui rejoue les mêmes fixtures `dict`/`CompactScoring`/`FullScoringSession` déjà présentes dans `test_delta_engine.py` avant/après le refactor et compare les `LapDeltaPacket` produits.

## Points ouverts

- **Emplacement de `VehicleBests`** : `simpulse/core/telemetry/` (Core, pas exposé aux plugins) vs `simpulse_sdk/models/` (SDK, potentiellement utile à un plugin qui inspecte lui-même `vehicles_src`) — à trancher avant l'étape 2 du plan. Penchant actuel : Core, `VehicleBests` n'a aucune raison d'être plugin-facing (aucun plugin ne reçoit de `vehicles_src` brut aujourd'hui).
- **`ScoringSnapshotFactory`** (item 5) : est-ce que `ScoringSnapshot` doit être un type totalement nouveau, ou peut-il réutiliser/étendre `BaseTimingState`/`FullGridScoringState` (`simpulse_sdk/models/scoring.py`), qui normalisent déjà une partie de ces mêmes champs pour le chemin `update_scoring_from_view()` ? Risque de créer un 3ᵉ modèle qui fait doublon avec les deux existants plutôt que 3 formats bruts + 1 modèle — à valider avant de coder.
