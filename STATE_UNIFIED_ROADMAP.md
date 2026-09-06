# SimPulse — Architecture « Source Unifiée » : état & suite

Document de travail pour aligner tout le monde sur la direction voulue.
Dernière mise à jour: branch `udp-dump`.

---

## 1. La vision (d'une phrase)

> Dans les plugins **race_engineer / HUD / autre**, il doit être **physiquement
> impossible** de piocher dans les données UDP brutes (`CompactScoring`,
> `FullScoringSession`, `TelemInfo`, …). Tous les plugins ne consomment que
> l'**état consolidé** exposé par le store (`timing`, `grid`, `delta`,
> propriétés 120 Hz) ou un **flux normalisé** (`VehicleSensors`,
> `LapDeltaPacket`), jamais les paquets de la couche transport.

La mise en place passe par un **modèle de données solide**, à deux couches
sémantiques:

- **`BaseTimingState`** (commun Compact/Full, ~10 Hz): session, timing, secteurs,
  tours, garage, validité, `track_length`.
- **`FullGridScoringState`** (Full uniquement, 2–5 Hz): grille complète,
  leaderboard, le joueur (`driver/vehicle/place/pénalités/pit stop`), météo,
  drapeaux.

---

## 2. Ce qui existe aujourd'hui dans le repo (état réel, commits)

Sur la branch `udp-dump` (au-dessus de `80bc658 SimPulse wip`):

| Commit | Objet |
|---|---|
| `bd1fd98` | **Secteurs HUD stabilisés** : le `DeltaEngine` remplit enfin `_last_sectorN_time/status` à chaque scoring (plus de secteurs terminés affichés `--`). Tests `test_sector_times_freeze.py`. |
| `f463a39` | **RaceEngineer lit le modèle unifié** : `context.manager/manager/sdk` passent par les façades `timing`/`grid` ; `player_vehicle` ajouté au modèle ; rôle+subroles ne touchent plus `compact_scoring.data`/`full_scoring.data`. |
| `082568c` | **Correction d'un leak singleton** : un contexte autonome ne lit plus le store global résiduel. |
| `3ddae9e` | **Hook technique métrologique** : `IChannelSampleSubscriber` + `ChannelSample(channel, len, ts)` (jamais le payload). `stream_diagnostics` migré dessus. |
| `c63be83` | **`TelemetryPluginView`** : les hooks `on_*` reçoivent une **vue** (accès consolidated) qui lève `AttributeError` sur tout slot raw UDP. |
| `3cab8c0` | **Exception RaceEngineer retirée** : plus **aucune** lecture raw dans `race_engineer` ni son SDK. |
| `7c0d005` | **`TelemetryWakeReason` supprimé** : plus d'enum, le nom du hook porte l'événement. Routeur if/elif supprimé partout. |

**Test complet** : `298 passed` sous Xvfb (seuls `glfw`/`lmu_hud_board` nécessitent un
écran X, échecs d'environnement non liés au code).

---

## 3. L'architecture cible (le « après »)

```text
isimotor_rawudp_client ──► (parsers core / ingestion)
        │                        ▼          (update_compact / update_full / update_telemetry / update_delta)
        │          TelemetryStateStore  (consolidation: timing / grid / delta / props 120Hz)
        │                        │
        │                        ▼
        │           TelemetryPluginView   (ce que voient les plugins)
        │                  timing · grid · delta · propriétés 120Hz
        │                  [compact_scoring / full_scoring / …] => AttributeError
        │                        │
        └─► PluginManager.dispatch_packet ─► on_<canal>(view) sur chaque plugin
                                                 + IChannelSampleSubscriber (len · ts · channel)
                                                      (métrologie uniquement)
```

Résumé des **canaux autorisés** donnés aux plugins:

| Canal | Contenu | Consommateur |
|---|---|---|
| État consolidé (vue) | `timing` / `grid` / `delta` / properties | rôles race_engineer, cockpit HUD |
| Normalisé haute-fréquence | `VehicleSensors` (hook `on_telemetry_frame`) | haptique, overlay |
| Delta packet | `LapDeltaPacket` (`on_delta_frame`) | HUD delta |
| Métrologie | `ChannelSample(channel, len, ts)` | stream_diagnostics |

### Règles à respecter
1. Un plugin ne lit Jamais `state.<slot>[]` (l'objet reçu ne les expose pas).
2. L'événement est identifié par le **nom du hook**, plus aucun enum `wake_reason`.
3. L'ingestion (écrire dans le store) se fait **uniquement** dans la couche parser/unifiée,
   jamais dans un plugin de comportement.
4. La distance voiture vient du flux delta (haute fréquence) ; le `track_length` (piste)
   vient du modèle de timing. Ne jamais les confondre (`lap_dist` du packet Compact =
   longueur piste vs `lap_dist` du Full/voiture = position).

---

## 4. « Quelle est la suite ? » — proposition priorisée

Tout ce qui suit est **recommandé** et bâti sur l'état ci-dessus. Il reste variable,
le chantier est « solide » mais peut encore gagner en couverture et en clarté.

### A. Verrouillage automatique du contrat (recommandé, rapide)
- Un test démontrant qu'un plugin qui tente `view.compact_scoring` (ou `.full_scoring`,
  `.telemetry`) reçoit une `AttributeError` (couverture automatique du « impossible »).
- Un test du hook `IChannelSampleSubscriber` qui reçoit channel/len/ts sans payload.
  → suite reste verte; rend la règle vérifiable par CI.

### B. Dette « ingestion » : plugin race_engineer
Le RaceEngineer ne lit plus de raw, mais il est encore **le point d'appel** de l'évaluation
(chaque hook `on_*` → `engineer.update()`). Si l'on veut que le store soit LA seule source
de déclenchement, options possibles, à trancher :
- B1. Garder tel quel (le hook `on_*` n'est plus qu'un « tick » de consolidation) ;
- B2. Fusionner les `on_*` en un seul point d'évaluation (le `CHANNEL_ROUTING` reste,
  mais tous les hooks appellent la même évaluation sur l'état) ;
Recommandation : **B2** (moins de surface, rôle sur état) — mais cela dépend des besoins
d'évaluation différenciée par canal.

### C. Vérifications post-refactoring
- Rendre `test_delta_engine`/`test_sector_times_freeze` des cas « bout en bout »
  (scoring Full+Compact+presque 100 Hz) pour sécuriser la stabilité des secteurs.
- Un schéma d'architecture d'une page (docs) résumant « qui lit quoi » (ce que ce fichier
  commence).

### D. (Optionnel) Suppression des choix d'API morts
- `TelemetryRawPacket` n'est plus qu'un wrapper interne ? (faire l'inventaire).
- Vérifier qu'aucun `Enum`/helper de canal non utilisé ne subsiste (ex. quelques
  `TelemetryChannel` listés mais jamais utilisés ne sont pas gênants).

### E. Ce qui n'est pas (encore) couvert / connus
- Les plugins overlay/Qt utilisent l'écran (nécessitent xvfb) → non bloquant.
- L'unicité du `DeltaEngine` est assurée par `ReferenceLapManager` ; ne pas dupliquer.

---

## 5. Comment je propose de l'implémenter

Si tu dis « GO sur A » : j'ajoute `tests/test_raw_slot_privacy.py` (3-4 cas :
AttributeError sur tout slot ; hook sample ; rien de cassé) + éventuellement B2 en
séparé si tu confirmes. Chaque étape est committée et testée (`298` au minimum).

---

## 6. S'il faut discuter avant

Tu me dis : **(1)** priorité A/B2 ou rien d'autre, **(2)** souhaites-tu qu'on fasse le
schéma d'architecture « one-page » et où le stocker (README ? `docs/architecture.md` ?).
Je m'en occupe après ta réponse.
