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

## 3. TODO — dette identifiée, pas encore traitée

Rien ci-dessous n'est bloquant ; classé par impact.

### T1. Frontière SDK/Core encore percée : `ReferenceLapProfile` vit dans le Core
`simpulse/core/telemetry/reference_profile.py` définit `ReferenceLapProfile`/
`TrackAnnotation`/`AnnotationType` — un type de données pourtant consommé par
des sous-plugins qui ne devraient connaître que le SDK. 14 fichiers importent
ce module directement (`grep -rln "reference_profile import"`), dont 3
builtin_plugins déjà nettoyés cette session (ils ne touchent plus
`ReferenceLapManager`, mais importent encore le *type* depuis `simpulse.core`).
**Fix propre** : déplacer ces 3 classes vers `simpulse_sdk.models`, garder un
ré-export shim dans `simpulse/core/telemetry/reference_profile.py` pour ne pas
casser les 14 call sites d'un coup, migrer les imports progressivement.

### T2. 23 fichiers `builtin_plugins/` importent `simpulse.core.*` directement
Pattern répandu, pas nouveau (préexistant à cette session). À auditer un par un :
certains sont légitimement "code de confiance" à la frontière (comme
`race_engineer/manager.py`), d'autres devraient plutôt passer par le SDK/la
View. Pas de plan concret pour l'instant — juste un inventaire à faire
(`grep -rl "^from simpulse\.core\.\|^import simpulse\.core\." simpulse/builtin_plugins/`).

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
