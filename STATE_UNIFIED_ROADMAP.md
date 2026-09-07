# SimPulse — Architecture « Source Unifiée » : état & suite

Document de travail pour aligner tout le monde sur la direction voulue.
Dernière mise à jour : branch `udp-dump`, après la refonte UDPServer / LMUParser /
TelemetryStateStore → `TelemetryView`.

---

## 1. La vision (d'une phrase)

> Dans les plugins **race_engineer / HUD / autre**, il doit être **physiquement
> impossible** de piocher dans les données UDP brutes (`CompactScoring`,
> `FullScoringSession`, `TelemInfo`, …), ni dans les singletons du **Core**
> (`ReferenceLapManager`, `DeltaEngine`, …). Tous les plugins ne consomment que
> l'**état consolidé et immutable** exposé par le SDK (`TelemetryView` :
> `timing`, `grid`, `delta`, propriétés dérivées) ou un flux normalisé
> (`VehicleSensors`, `LapDeltaPacket`), jamais la couche transport ni le Core.

---

## 2. Ce qui existe aujourd'hui (état réel, post-refonte)

### Pipeline de production — un seul point de fusion par paquet

```text
UDP datagram
   │
   ▼
UDPServer (I/O pur : socket, décodage, callback unique — plus de cache interne)
   │  packet_listener(channel, raw_packet, len)
   ▼
TelemetryBus.process_raw_packet()          ← ORCHESTRATEUR UNIQUE
   │
   ├─ 1. store.update_<type>(raw_packet, ts)        [UNE SEULE FOIS]
   ├─ 2. Engines consomment la View du Store :
   │        reference_lap_mgr.update_physics_from_view(store.snapshot())
   │        reference_lap_mgr.update_scoring_from_view(store.timing, store.grid)
   ├─ 3. packet_received.emit(packet)   → PluginManager.dispatch_packet(view=store.snapshot())
   │        (émis APRÈS l'étape 2 : la View que voient les plugins inclut déjà
   │         le delta du tick courant, pas celui du tick précédent)
   └─ 4. sensors = VehicleSensors.from_view(store.snapshot()) → UI/overlay
```

- **`TelemetryStateStore`** (`simpulse_sdk/models/state_store.py`) reste la seule
  source de vérité mutable ; sa logique de fusion (`update_telemetry`/
  `update_compact_scoring`/`update_full_scoring`/…) est inchangée et correcte.
  Nouveauté : `store.snapshot() -> TelemetryView`.
- **`TelemetryView`** (`simpulse_sdk/models/view.py`, nouveau) : `@dataclass(frozen=True)`,
  même famille que `LapDeltaPacket`. Remplace `TelemetryPluginView` (ancien proxy
  mutable en direct sur le Store) — c'est un vrai instantané figé, données +
  résultat des Engines (`delta`).
- **`DeltaEngine`/`ReferenceLapManager`** ont maintenant `update_physics_from_view()`
  en plus de `update_scoring_from_view()` (déjà existant) — les deux chemins
  d'ingestion passent par la View, plus par un paquet brut extrait à la main.
- **`LMUParser` supprimé.** Il ne faisait plus qu'un aller-retour redondant
  (paquet → Store, une 2e/3e/4e fois) pour reconstruire un `VehicleSensors` que
  `VehicleSensors.from_view(view)` fait maintenant directement depuis la View.
- **`UDPServer`** vidé de tout code mort/cassé (`_latest_data`, `_handle_*`,
  `get_latest_*`) — pur I/O réseau.
- **`PluginManager.dispatch_packet`** ne touche plus le Store lui-même (le merge
  est fait une fois par `TelemetryBus` avant l'émission du signal) ; il construit
  la `TelemetryView` et la passe aux hooks `on_*`.

### Garde-fous SDK déjà en place
1. Un plugin ne lit jamais `view.<slot brut>` (le champ n'existe pas sur le
   dataclass — `AttributeError` structurelle, pas un filtre `__getattr__`).
2. `race_engineer/manager.py` est le **seul** endroit autorisé à résoudre le
   profil de référence depuis le Core (`ReferenceLapManager`) — il l'injecte
   ensuite en donnée plate dans `EngineerContext`, une fois par tick. Les
   sous-plugins (`pace_notes`, `traffic_jam`, `traffic_spotter`) ne reçoivent
   plus jamais d'accès direct au Core : ils mémorisent la dernière valeur reçue
   via le contexte (`_last_known_profile`).

**Suite complète : 337/337 tests passent.**

---

## 3. TODO — dette identifiée

### T1. ✅ Frontière SDK/Core percée par `ReferenceLapProfile` — traité cette session
**Le déplacement brut envisagé initialement était une mauvaise idée** (repéré en
cours de session) : `ReferenceLapProfile` n'est pas qu'un type de données, c'est
un objet mutable propriétaire de logique Core — enregistrement meter-by-meter,
édition d'annotations, autosave/load vers `.json`/`.marks.json`. Le déplacer tel
quel dans le SDK aurait fait fuir du code Core (I/O disque, mutation) dans la
couche censée n'exposer que de l'état consolidé immuable.

**Fix retenu** (même famille que `TelemetryView`/`TelemetryStateStore.snapshot()`) :
- `ReferenceLapProfile`/`TrackAnnotation` restent dans
  `simpulse/core/telemetry/reference_profile.py` (Core, mutable, I/O, inchangé).
- `AnnotationType` (enum, pur type-valeur) déménage dans
  `simpulse_sdk.models.reference_profile` — source unique, Core l'importe en retour.
- Nouveau `ReferenceLapProfileView`/`TrackAnnotationView` dans le même module SDK :
  `@dataclass(frozen=True)`, grids en `tuple`, uniquement les helpers en lecture
  pure réellement consommés par les sous-plugins (`get_value_at_dist`,
  `get_annotation_display_label`, `get_annotation_phrase_key`, `get_sector_at_dist`,
  `get_turn_number`, `get_sorted_turns`) — zéro I/O, zéro mutation.
- `ReferenceLapProfile.to_view() -> ReferenceLapProfileView` : construit
  l'instantané. Seul `race_engineer/manager.py::_get_active_reference_profile()`
  (et le fallback historique dans `context.py::get_reference_profile()`, voir T2)
  appelle `.to_view()` — les sous-plugins (`pace_notes`, `traffic_jam`,
  `traffic_spotter`) et `EngineerContext` ne connaissent plus que
  `ReferenceLapProfileView`.

Suite complète toujours verte après le fix (337/337).

### T2. Audit `builtin_plugins/` important `simpulse.core.*` directement — fait
22 fichiers (`grep -rl "^from simpulse\.core\.\|^import simpulse\.core\." simpulse/builtin_plugins/`,
proche des ~23 déjà notés). Catégorisation :

1. **Faux positifs — shims déjà en place** (la majorité) : `simpulse.core.telemetry.state_store`,
   `simpulse.core.telemetry_channels`, `simpulse.core.telemetry.sensors`,
   `simpulse.core.params` ne sont *que* des ré-exports 1:1 de `simpulse_sdk` (mêmes
   docstrings "Re-exported from simpulse_sdk for single source of truth"). Import
   d'un chemin Core qui pointe en réalité vers le SDK — cosmétique, pas une fuite
   de frontière. Concerne `haptic_feedback/*`, la plupart des sous-plugins
   `race_engineer/*`, `official_cockpit_hud/widgets/base_widget.py`.
2. **Services Core légitimes, hors du périmètre de la vision** :
   `simpulse.core.utils.audio` (`AudioAnnouncer`) / `audio_baker` — TTS/lecture
   audio, pas de la donnée télémétrie/UDP. Pas une violation du principe (le
   principe porte sur les données de course, pas les services transverses).
3. **Violation réelle #1 — déjà documentée** : `race_engineer/manager.py` résout
   `ReferenceLapManager`/`DeltaEngine` (Core) — accepté comme unique point
   d'entrée légitime (cf. §2 point 2).
4. **Violation réelle #2 — ✅ corrigée** :
   `EngineerContext.get_reference_profile()` (`race_engineer/context.py`) avait
   un chemin de repli qui reconstruisait `ReferenceLapManager.get_instance()`
   directement quand `self.reference_profile` était `None` mais qu'un
   `scoring`/`store` était présent — donc `context.py` n'était *pas* le seul
   point d'entrée Core comme l'affirmait §2 point 2. Fallback supprimé : la
   méthode ne retourne plus que `self.reference_profile` (injecté une fois par
   tick par le manager), `None` sinon — aucun appelant ne retombe plus sur le
   singleton global ou son résidu inter-tests. 337/337 toujours verts (les 3
   tests d'intégration `test_manager_domain_filter_integration.py` passaient
   déjà par `RaceEngineer.update()`, donc par le point d'entrée légitime de
   `manager.py`, pas par ce fallback).
5. **Violation réelle #3 — ✅ en grande partie corrigée** :
   `race_engineer/subplugins/lap_validity.py::_evaluate_validity()` prenait un
   paramètre `state: TelemetryStateStore` mort (jamais transmis autrement que
   via `context`, et aucun appelant — code ou test — n'invoque ces hooks avec
   `context=None`) avec deux branches de repli (`isinstance(state, ...)` /
   `TelemetryStateStore.get_instance()`) jamais exercées. Supprimées ; la
   fonction ne prend plus que `context` et lit `context.state_store`. Plus
   sérieux : `reset()` appelait `TelemetryStateStore.get_instance().reset()` —
   un vrai bug de blast radius, puisque `RaceEngineer.set_role_enabled(role_id,
   False)` appelle `slot.reset()`, donc désactiver *ce seul rôle* depuis l'UI
   remettait à zéro l'état télémétrie **global** lu par tous les autres
   rôles/plugins. Supprimé — `reset()` ne touche plus que son propre état
   interne. `get_state_summary()` garde un accès direct en lecture seule à
   `TelemetryStateStore.get_instance()` (pas de mutation, pas de `context`
   disponible dans sa signature pour un affichage de statut UI hors-tick) —
   accepté tel quel, pas une violation du même ordre. (`emit_sound()` ne touche
   en réalité pas le Store du tout — juste `TrackLimitsLogger`, un service Core
   distinct — l'inventaire initial le citait par erreur.)
6. **`reference_lap_studio/plugin.py`** importe `simpulse.core.reference_lap`
   (le `ReferenceLapManager` lui-même) — légitime : c'est l'UI Studio dédiée à
   l'édition/l'enregistrement des profils de référence, pas un plugin
   race_engineer/HUD consommateur de données de course.

7. **Violation réelle #4 — signalée par MGT directement dans le code — ✅ corrigée**,
   et généralisée : `TelemetryView.raw_scoring` (`Union[FullScoringSession,
   CompactScoring]`) est **supprimé** de `TelemetryView`. C'était la demande de
   fond ("un modèle unifié de full et compact avec un merge qui porte toute la
   difficulté et piège") : le vrai problème n'était pas seulement ce champ,
   c'est que **`BaseTimingState`/`FullGridScoringState` étaient reconstruits en
   double** — `update_compact_scoring()` et `update_full_scoring()`
   (`simpulse_sdk/models/state_store.py`) recopiaient chacun à la main le même
   sous-ensemble de ~11 champs (`total_laps`, `count_lap_flag`, `cur_sector1/2`,
   `last_*`, `best_*`, …) depuis deux formes différentes (`CompactScoring` vs
   `FullScoringSession.player_vehicle`, un `VehicleScoring`) — deux littéraux à
   maintenir identiques à l'œil, le vrai piège (un champ ajouté/renommé dans un
   chemin et oublié dans l'autre désynchronise silencieusement `timing` selon
   le paquet arrivé en dernier, sans qu'aucun test ne le voie).
   **Fix** (`simpulse_sdk/models/scoring.py`) :
   - `BaseTimingState.merge(...)` : point de fusion unique, prend un
     `lap_source: LapTimingSource` (Protocol structurel satisfait aussi bien
     par `CompactScoring` que par `VehicleScoring` — même noms de champs par
     coïncidence du format isiMotor) + les champs de session résolus par
     l'appelant (`track_name`, `session`, `track_length`, …).
   - `FullGridScoringState.from_timing(timing, **full_only_fields)` : construit
     le grid à partir du `timing` déjà fusionné (jamais retypé une 2e fois) +
     les champs propres à Full (météo, pénalités, leaderboard, …).
   - `FullGridScoringState.sync_lap_timing(timing)` : resynchronise en place
     les champs hérités de `BaseTimingState` sur le grid existant quand un tick
     CompactScoring (10Hz) arrive entre deux ticks FullScoringSession (2-5Hz) —
     itère sur `dataclasses.fields(BaseTimingState)`, donc un champ ajouté là
     est repris ici automatiquement (plus de liste à maintenir à la main).
   - `update_compact_scoring`/`update_full_scoring` n'ont plus qu'à appeler
     `.merge()`/`.from_timing()`/`.sync_lap_timing()` — ~60 lignes de littéraux
     dupliqués supprimées.
   - Trap documenté en commentaire dans `update_full_scoring` : si
     `player_veh` reste `None` ce tick, `self.timing`/`self.grid` ne sont PAS
     mis à jour du tout (comportement conservé, juste rendu explicite).
   - Conséquence directe sur `TelemetryView` : `VehicleSensors.from_view()`
     dérive maintenant `remaining_laps` depuis `view.timing.max_laps`/
     `.total_laps` (déjà unifiés) au lieu de transmettre `raw_scoring` à
     `VehicleSensors.from_telem_info()` pour qu'il refasse un `isinstance`
     dispatch à 3 branches (`CompactScoring`/`FullScoringSession`/dict JSON
     legacy) — ce triple dispatch reste nécessaire dans `from_telem_info()`
     lui-même (API bas niveau encore appelée directement par un test avec un
     paquet brut), mais un nouveau paramètre `remaining_laps` explicite permet
     de le court-circuiter ; `raw_scoring` n'avait plus aucun autre
     consommateur et a donc pu être retiré de `TelemetryView` sans détour.

**Section 3 entièrement traitée** (T1/T2, items 1-7). Reste T3 (vérif manuelle,
hors de portée agent) et T4 (nettoyages mineurs, voir ci-dessous).

### T3. Vérification manuelle sur session UDP réelle
Le nouveau séquencement (merge → Engines → dispatch plugins) change délibérément
le timing : les plugins voient maintenant le delta du tick courant au lieu de
celui du tick précédent. Comportement attendu meilleur, mais jamais vérifié en
conditions réelles (jeu qui tourne). À faire avant de considérer le pipeline
pleinement validé en prod.

### T4. Nettoyages mineurs déjà repérés, pas traités
- `TelemetryStateStore.player_lap_dist` (state_store.py) est la seule
  `@property` du Store sans son propre `with self._mutex:` (délègue à
  `self.lap_dist`, qui l'a — pas de bug fonctionnel, juste une incohérence de
  style).
- `DeltaEngine.update_scoring()`/`update_physics()` (chemins paquet brut) gardés
  comme filet de sécurité pour d'éventuels appelants directs restants. À
  supprimer une fois confirmé qu'aucun test/appelant n'en a plus besoin.
- Les ~40 `@property` scalaires ad hoc du Store (`speed_kmh`, `gear`, `fuel`,
  …) gardées pour compat interne, mais plus aucun consommateur externe
  (Engines/Plugins) n'est censé y toucher directement — tout doit passer par
  `TelemetryView`. À supprimer une fois ce sevrage confirmé par grep.
- Renommage `update_*` → `merge_*` sur le Store (discuté, pas fait — jugé trop
  invasif pour le gain, cf. décision prise pendant la refonte).

---

## 4. Historique (pré-refonte, pour mémoire)

Sur la branch `udp-dump` (au-dessus de `80bc658 SimPulse wip`), avant la
refonte UDPServer/LMUParser/State de cette session :

| Commit | Objet |
|---|---|
| `75169f6` | Phase B SRP — `track_cut_state` devient une propriété calculée du Store |
| `4cc9208` | Phase A SRP — suppression du calcul mort/dupliqué de LMUParser |
| `d2ebd98` | Phase C SRP — hystérésis garage/pause unifiée dans `PresenceTracker` |
| `cb4f84d` | Phase 2 SRP — les engines consomment la View, LMUParser arrête de dupliquer DeltaEngine |
| `49ceac2` | Séparation secteur raw (input engine) / secteur guardé (affichage) |

Ces phases avaient déjà établi le pattern "Engine consomme la View" pour le
scoring (`update_scoring_from_view`) et la fusion centralisée dans le Store —
la refonte de cette session (UDPServer/LMUParser/View immutable) en est la
suite directe, pas une remise à zéro.
