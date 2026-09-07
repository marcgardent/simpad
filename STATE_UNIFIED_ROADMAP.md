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
4. **Violation réelle #2 — nouvellement repérée, pas corrigée** :
   `EngineerContext.get_reference_profile()` (`race_engineer/context.py`) a un
   chemin de repli qui reconstruit `ReferenceLapManager.get_instance()`
   directement quand `self.reference_profile` est `None` mais qu'un
   `scoring`/`store` est présent — donc **`context.py` n'est pas le seul point
   d'entrée Core comme l'affirmait §2 point 2**. Corrigé cette session pour au
   moins retourner `.to_view()` (cohérence de type), mais le court-circuit vers
   `ReferenceLapManager` lui-même reste en place — un vrai fix supprimerait ce
   fallback et forcerait tous les appelants à toujours passer par
   `EngineerContext.reference_profile` injecté par le manager.
5. **Violation réelle #3 — nouvellement repérée, pas corrigée, plus sérieuse** :
   `race_engineer/subplugins/lap_validity.py::_evaluate_validity()` /
   `emit_sound()` / `reset()` / `get_state_summary()` font
   `TelemetryStateStore.get_instance()` en direct (import local dans la
   fonction) et appellent des méthodes *mutantes* du Store
   (`consume_validity_transition()`, `.reset()`) — pas juste une lecture. Le
   chemin normal (`context.state_store`) est toujours pris en pratique (le
   `context` passé par `role_base` n'est jamais `None`), donc pas de bug
   observé, mais le code est écrit pour retomber sur le singleton mutable si un
   jour `context` devient `None` (ou en test unitaire isolé). À corriger :
   supprimer les branches `elif`/`else` de `_evaluate_validity` et les 3 accès
   directs de `reset()`/`get_state_summary()`/`emit_sound()`, en s'appuyant
   uniquement sur `context.state_store`.
6. **`reference_lap_studio/plugin.py`** importe `simpulse.core.reference_lap`
   (le `ReferenceLapManager` lui-même) — légitime : c'est l'UI Studio dédiée à
   l'édition/l'enregistrement des profils de référence, pas un plugin
   race_engineer/HUD consommateur de données de course.

7. **Violation réelle #4 — signalée par MGT directement dans le code, pas
   corrigée** : `TelemetryView.raw_telemetry`/`raw_scoring` (`simpulse_sdk/models/view.py`)
   exposent encore une union brute `Union[FullScoringSession, CompactScoring]`
   au lieu d'un état consolidé — contraire au principe même de la View ("bug
   assuré" selon l'annotation laissée sur le champ). Ces deux champs existent
   pour les Engines/`VehicleSensors.from_view()` en aval, pas pour les plugins
   — mais tant qu'ils vivent sur la View partagée, rien n'empêche un plugin de
   les lire directement. À corriger : soit les sortir de `TelemetryView` vers
   un canal interne dédié aux Engines, soit les remplacer par leur forme déjà
   consolidée (`timing`/`grid`).

**Reste à faire** (pas traité cette session, effort ciblé plutôt qu'un audit) :
items 4, 5 et 7 ci-dessus.

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
