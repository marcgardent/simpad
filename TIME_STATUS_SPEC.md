# TimeStatus — Spec

## Contexte

Depuis le début de cette branche, quasiment tous les bugs (best lap qui ne s'affiche pas, vert/jaune qui ne marchent pas sur les secteurs, badge de tour qui utilise une règle différente des secteurs, "MY BEST" vide alors que le jeu l'envoie) viennent de la même cause : **il n'y a pas UN modèle qui représente "où j'en suis par rapport aux références"**. À la place, il y a des dizaines de champs plats, calculés à des endroits différents, avec des règles de couleur dupliquées (`SplitStatus`, `LapColorStatus`, `ExpectedStatus` — trois enums qui encodent presque la même chose), recalculés à 100Hz alors que la plupart ne changent que quelques fois par session.

État actuel, concrètement (`simpulse_sdk/models/delta.py`) :
```python
expected_sector1_time / expected_sector1_status / expected_sector1_is_pr
expected_sector2_time / expected_sector2_status / expected_sector2_is_pr
expected_sector3_time / expected_sector3_status / expected_sector3_is_pr
expected_lap_is_pr
my_session_best_lap_time_str
session_best_lap_time_str
sector1_time / sector1_status / sector1_delta   (x3, doublon partiel des expected_*)
last_lap_time / last_lap_time_str / last_lap_status / last_lap_is_pr
```
9 fields rien que pour les secteurs "expected", 3 enums de couleur différents, et une règle de couleur pour le badge de tour qui a vécu **indépendamment** de celle des secteurs pendant des mois (bug corrigé cette session, mais qui n'aurait jamais dû exister).

**Objectif** : un seul modèle de vérité, `TimeStatus`, construit par un Engine dédié, injecté dans `DeltaEngine`, qui remplace tous les champs plats ci-dessus.

## Modèle de domaine

Nouveau module SDK : `simpulse_sdk/models/timing.py`. Tout est `@dataclass(frozen=True)`, plugin-facing, aucune logique métier dedans (juste des getters de formatage — même style que `ReferenceLapProfileView`).

```python
@dataclass(frozen=True)
class TimeLap:
    """Un chrono figé : le temps par secteur + total. Rien de plus — pas de
    delta, pas de couleur. C'est la donnée brute d'un tour de référence
    (mien, du paddock, ou all-time)."""
    sector1: float = 0.0
    sector2: float = 0.0
    sector3: float = 0.0
    total: float = 0.0

    @property
    def is_valid(self) -> bool:
        return 0.0 < self.total < 999900.0

    # formatters (délèguent à simpulse_sdk.format_lap_time / format_sector_time)
    @property
    def total_str(self) -> str: ...
    @property
    def sector1_str(self) -> str: ...
    @property
    def sector2_str(self) -> str: ...
    @property
    def sector3_str(self) -> str: ...


class TimeTarget(str, Enum):
    """Quelle référence SESSION-scoped est actuellement battue — la SEULE
    source de vérité pour la couleur, remplaçant SplitStatus/LapColorStatus/
    ExpectedStatus. Ordre croissant = priorité d'affichage (le plus fort
    gagne). Volontairement séparé de la couleur elle-même (voir "Résolution
    couleur" plus bas) : le domaine dit CE QUI est vrai, la vue décide
    comment le peindre.

    PAS de membre ALLTIME ici (erreur de la 1ère version de ce doc) : mon
    all-time-best et le paddock-best ne sont PAS deux niveaux d'un même ordre
    total — rien ne garantit que paddock <= all-time (le paddock peut très
    bien être plus lent que mon propre record). Les coder dans le même enum
    créait une collision : on ne peut pas représenter "je bats le paddock ET
    mon record perso" (deux faits indépendants) avec une seule valeur qui ne
    peut en porter qu'un à la fois. "Bat mon all-time-best" est un fait
    orthogonal à la couleur session — voir `is_personal_record_target` plus bas,
    calculé séparément, jamais mélangé à `target`.
    INVALID délibérément absent aussi : un tour/secteur invalidé a déjà son
    propre indicateur sonore/visuel ailleurs ; ce n'est pas le sujet de ce
    doc et `target` ne doit pas être utilisé pour cacher delta/expected."""
    NONE = "none"          # rien à comparer (pas de référence chargée) -> blanc
    BEHIND = "behind"      # référence(s) connue(s), mais aucune battue -> jaune
    SESSION = "session"    # bat MY SESSION BEST -> vert
    PADDOCK = "paddock"    # bat PADDOCK BEST -> violet


@dataclass(frozen=True)
class TimeSectorViewModel:
    target: TimeTarget = TimeTarget.NONE
    expected_time: float = 0.0   # projection = référence active + delta courant
    delta_time: float = 0.0      # écart courant vs référence active
    is_current: bool = False     # ce secteur est celui en cours (vs déjà figé)
    # Fait indépendant de `target` (voir docstring TimeTarget) — jamais dérivé,
    # toujours résolu séparément par resolve_is_personal_record_target().
    is_personal_record_target: bool = False

    @property
    def expected_time_str(self) -> str: ...
    @property
    def delta_str(self) -> str: ...        # "+0.234" / "-0.150" / "--"


@dataclass(frozen=True)
class TimeLapViewModel:
    target: TimeTarget = TimeTarget.NONE
    expected_time: float = 0.0
    delta_time: float = 0.0
    is_personal_record_target: bool = False   # idem, indépendant de target

    @property
    def expected_time_str(self) -> str: ...
    @property
    def delta_str(self) -> str: ...


@dataclass(frozen=True)
class WallOfFameTimes:
    """Les trois références connues à l'instant T. Un TimeLap par référence
    — pas de statut/couleur dedans, ce sont des FAITS, pas une vue."""
    my_best_all_time: TimeLap = field(default_factory=TimeLap)
    my_best_session: TimeLap = field(default_factory=TimeLap)
    paddock_session_best: TimeLap = field(default_factory=TimeLap)


@dataclass(frozen=True)
class TimeStatus:
    """LE modèle que DeltaEngine produit à chaque tick et que les plugins
    consomment. Remplace tous les champs plats expected_sectorN_*/
    expected_lap_is_pr/sector1_status/etc. de LapDeltaPacket.

    ⚠️ AMENDEMENT (implémentation, tranché avec l'utilisateur) : `wall_of_fame`
    ajouté ici. La 1ère version de ce doc renvoyait `my_session_best_lap_time_str`/
    `session_best_lap_time_str` vers "time_status.lap (target == SESSION/PADDOCK)"
    — faux : `lap`/`sectors` ne portent que la PROJECTION courante (target/
    expected/delta), jamais la valeur brute d'une référence ("MY SESSION BEST:
    1:32.450" doit s'afficher texto, indépendamment de si le tour en cours la
    bat). `wall_of_fame` porte cette donnée brute (voir `TimeLap.total_str`)
    à côté de la projection, sur le même modèle."""
    lap: TimeLapViewModel = field(default_factory=TimeLapViewModel)
    sectors: Tuple[TimeSectorViewModel, TimeSectorViewModel, TimeSectorViewModel] = (
        field(default_factory=TimeSectorViewModel),
        field(default_factory=TimeSectorViewModel),
        field(default_factory=TimeSectorViewModel),
    )
    wall_of_fame: WallOfFameTimes = field(default_factory=WallOfFameTimes)

    @property
    def sector1(self) -> TimeSectorViewModel: return self.sectors[0]
    @property
    def sector2(self) -> TimeSectorViewModel: return self.sectors[1]
    @property
    def sector3(self) -> TimeSectorViewModel: return self.sectors[2]
```

## Résolution : deux fonctions indépendantes, jamais fusionnées

Remplacent `sector_colors.expected_status()` et `sector_colors.sector_split_status()` (les deux implémentations actuelles). **Deux fonctions séparées, pas une** — c'est le point central de cette révision : `target` (couleur session-scoped) et `is_personal_record_target` (bat mon all-time-best) sont deux faits indépendants, jamais mélangés dans une seule valeur.

```python
def resolve_target(
    current: float, wof: WallOfFameTimes, key: Literal["total","sector1","sector2","sector3"],
    eps: float,
) -> TimeTarget:
    """Priorité : PADDOCK > SESSION > BEHIND > NONE. Ne regarde JAMAIS
    wof.my_best_all_time — voir resolve_is_personal_record_target ci-dessous."""
    paddock = getattr(wof.paddock_session_best, key)
    session = getattr(wof.my_best_session, key)
    if <paddock valide> and current <= paddock + eps: return PADDOCK
    if <session valide> and current <= session + eps: return SESSION
    if <session ou paddock connu>: return BEHIND
    return NONE


def resolve_is_personal_record_target(
    current: float, wof: WallOfFameTimes, key: Literal["total","sector1","sector2","sector3"],
    eps: float,
) -> bool:
    """Indépendant de resolve_target. Ne regarde QUE wof.my_best_all_time."""
    ever = getattr(wof.my_best_all_time, key)
    if not <ever valide>:
        return False
    return current < ever - eps   # strictement meilleur, voir note ci-dessous
```

Note : `current < ever - eps` (strict, pas `<=`) est le correctif du bug "PR actif par défaut" de cette session — à l'instant où `current == ever` exactement (mode all-time-best, delta=0 au tout début d'un tour), ce n'est PAS encore un record battu.

**`eps` : paramètre obligatoire, PAS une constante du domaine.** `sector_colors.py` actuel fixe `EPS = 0.001` en dur — à 1ms, il n'a aucun effet réel (aucune mesure UDP n'est jamais "à égalité" à la milliseconde près, donc la branche `<=` équivaut en pratique à `<`). La tolérance d'égalité qui a un sens pour un pilote (est-ce que je considère "à égalité" comme "j'ai battu la référence") est une décision d'affichage, pas une vérité du domaine — donc `resolve_target`/`resolve_is_personal_record_target` prennent `eps` en paramètre, fourni par l'appelant (le plugin HUD, via sa config), pas codé en dur dans `simpulse_sdk`. Valeur recommandée par défaut côté vue : **±0.1s** (100ms), configurable dans le plugin cockpit — pas 0.001.

**Table de rendu** (propriété de la VUE, pas du domaine — vit dans les widgets, pas dans `simpulse_sdk`) :

| target    | couleur badge secteur | couleur badge tour |
|-----------|-----------------------|---------------------|
| NONE      | blanc                 | blanc               |
| BEHIND    | jaune                 | jaune               |
| SESSION   | vert                  | vert                |
| PADDOCK   | violet                | violet              |

`is_personal_record_target` s'affiche en plus, en overlay (tag texte "PR" blanc, jamais une couleur — convention "no pink" déjà en place) — **quel que soit `target`** : on peut très bien battre son all-time-best (ever plus lent que le paddock, cas réel) tout en étant `target=SESSION` ou même `target=BEHIND`. C'est exactement le cas que l'enum unique précédent ne pouvait pas représenter.

`INVALID` (tour/secteur coupé) : hors scope de ce doc — indicateur sonore/visuel déjà existant ailleurs, ne doit pas passer par `target` ni cacher `expected_time`/`delta_time`.

## Vue : quand cacher le delta (répond au point ouvert de la version précédente)

La version précédente de ce doc laissait un point ouvert sur les "deltas de secteur en cours" sans vraiment poser de question — corrigé ici avec une vraie règle, tranchée :

`TimeStatus` calcule et expose `expected_time`/`delta_time` en continu, y compris avant qu'un secteur/tour ait vraiment commencé (le domaine ne "cache" jamais rien — il dit juste la vérité à l'instant T, même si à cet instant `delta=0` par construction). **C'est la VUE (l'overlay) qui décide de ne rien afficher** tant que le secteur/tour n'est pas réellement engagé.

Cette fenêtre de gel existe déjà et n'est pas à réinventer : `DeltaEngine.freeze_duration` (3.5s par défaut, `ReferenceLapManager.set_freeze_duration()`, déjà paramétrable dans le plugin cockpit) et `is_lap_freeze_active`/`is_current` sur `VehicleSensors`/`TimeStatus`. Règle d'affichage pour un widget qui consomme `TimeStatus` :
- secteur/tour dont `is_current=False` et hors fenêtre de gel → ne rien afficher (case vide, pas de "0.000" ni de couleur).
- secteur/tour `is_current=True` (en cours) → afficher `delta_time`/`target` en direct, comme aujourd'hui.
- **juste après la ligne, pendant `freeze_duration` → afficher `expected_time_str` (le TEMPS du secteur/tour qui vient de finir, pas `delta_str`)**. Correction par rapport à la version précédente de ce doc, qui disait à tort "delta/statut figé". C'est le comportement déjà en place aujourd'hui (`sector_times.py` : delta tant que `is_current`, sinon le split time figé `s_time`) — `TimeStatus` ne fait que le formaliser : à l'instant précis où un secteur/tour se termine, `expected_time` (= référence + delta final) **est** le temps réel obtenu, donc `expected_time_str` porte déjà la bonne valeur à afficher pendant le gel, sans champ supplémentaire.

## Engine

### `WallOfFameEngine` (nouveau, `simpulse/core/telemetry/wall_of_fame_engine.py`)

Rôle unique : maintenir `WallOfFameTimes` à jour. Remplace, en les regroupant dans UN composant testable isolément (même pattern que `SectorEngine`, déjà extrait de `DeltaEngine` il y a deux sessions) :
- `DeltaEngine._all_time_best_lap_time` / `_all_time_best_profile` (+ ses splits dérivés via `_individual_sector_splits`)
- `DeltaEngine._game_session_best_lap_time` (le fix de cette session — source de vérité pour `my_best_session.total`)
- `DeltaEngine._session_best_lap_time` (notre propre capture — devient un simple fallback si le jeu n'a pas encore reporté, comme déjà fait dans `_session_lap_bound`)
- `DeltaEngine._paddock_best_lap` / `_paddock_cum_s1` / `_paddock_cum_s2` (paddock lap — celui-ci EXCLUT déjà le joueur, `_is_player(v): continue`)

⚠️ `SectorEngine.session_split_best_s1/s2/s3` (`sector_engine.py:183-217`, `update_session_bests`) — **tranché : paddock+moi-même**, confirmé en relisant le code (`for v in vehicles_src: ...` sans filtre `_is_player`, contrairement à la version lap ci-dessus). `WallOfFameEngine` ne peut donc PAS réutiliser ces champs tels quels pour `WallOfFameTimes.paddock_session_best` : se comparer à un minimum qui peut être son propre meilleur split rendrait `target=PADDOCK` trivialement vrai en permanence. `WallOfFameEngine` doit calculer sa propre agrégation paddock-only pour les splits (même filtre `_is_player` que `_paddock_best_lap`), pas réutiliser `session_split_best_s1/s2/s3` en l'état.

API :
```python
class WallOfFameEngine:
    def update_from_scoring(self, ..., vehicles_src: list) -> None: ...
    def update_from_lap_completed(self, lap: TimeLap, is_valid: bool) -> None: ...
    def load_all_time_from_disk(self, profile: ReferenceLapProfile) -> None: ...
    def reset_session(self) -> None: ...   # track/car change
    def snapshot(self) -> WallOfFameTimes: ...
```

### `DeltaEngine` (modifié)

Compose `WallOfFameEngine` (`self._wall_of_fame = WallOfFameEngine()`), exactement comme il compose déjà `SectorEngine` (`self._sectors`). Reçoit aussi `eps` — même pattern que `freeze_duration` déjà en place : `self.time_status_eps: float = 0.1`, réglable via `ReferenceLapManager.set_time_status_eps()` depuis la config du plugin cockpit (pas une constante domaine, voir "eps" plus haut). À chaque tick où une position/delta est calculée :
1. Calcule la projection courante (déjà fait : `estimated_lap_time`, `_sectorN_delta`).
2. Appelle `resolve_target(..., eps=self.time_status_eps)` **et** `resolve_is_personal_record_target(..., eps=self.time_status_eps)` séparément, pour le tour et chaque secteur, contre `self._wall_of_fame.snapshot()` — jamais l'un dérivé de l'autre.
3. Construit et stocke `self._time_status: TimeStatus`.
4. Expose `self.time_status: TimeStatus` (property publique).

`ReferenceLapManager._build_delta_packet()` copie `de.time_status` dans un nouveau champ `LapDeltaPacket.time_status: TimeStatus`, et `TelemetryBus._apply_delta_fields` le copie dans `VehicleSensors.time_status`.

## Migration (par étapes, pas un big-bang)

Principe : marquer obsolète AVANT de construire le nouveau système, pas après — comme ça le linter/IDE donne une checklist exhaustive et vérifiée par l'outillage de tout ce qui reste à migrer, au lieu de compter sur un grep manuel qui peut en oublier.

**Étape 1 — marquer l'existant obsolète (comportement inchangé, zéro régression).**
Champs concernés : `LapDeltaPacket`/`VehicleSensors` — `expected_sectorN_time/status/is_pr` (x3), `expected_lap_is_pr`, `sector1/2/3_time/status/delta`, `my_session_best_lap_time_str`, `session_best_lap_time_str`, `last_lap_status`, `last_lap_is_pr`. Même mécanisme déjà en place dans ce repo pour les champs `WheelSet` legacy (`simpulse_sdk/models/telemetry.py:1302-1318`, `@property` + `@deprecated(...)` PEP 702) :
- `VehicleSensors` (dataclass mutable) : renommer le champ en `_xxx` (privé), exposer `xxx` en `@property @deprecated("Use sensors.time_status.… instead") def xxx(self): return self._xxx` + un setter qui écrit `self._xxx` — `TelemetryBus._apply_delta_fields` continue d'assigner exactement comme avant, sans changement de valeur ni de fréquence.
- `LapDeltaPacket` (frozen) : même idée, le champ constructeur devient `_xxx`, `xxx` devient une `@property @deprecated(...)` en lecture seule. Seul `ReferenceLapManager._build_delta_packet()` (site de construction unique) a besoin d'un renommage de kwarg.
Résultat : zéro changement de comportement, mais chaque site de lecture dans TOUT le repo s'allume comme obsolète dans l'IDE/linter. C'est la checklist de l'étape 3.

**Étape 2 — construire le nouveau système en parallèle.** Créer `simpulse_sdk/models/timing.py`, `WallOfFameEngine`, brancher dans `DeltaEngine`/`LapDeltaPacket`/`VehicleSensors` en AJOUTANT `time_status` à côté des champs (désormais dépréciés) de l'étape 1, qui restent fonctionnels et inchangés en parallèle. Tests unitaires sur `WallOfFameEngine`, `resolve_target` et `resolve_is_personal_record_target` isolément — y compris le cas "bat mon all-time-best sans battre le paddock" (target=SESSION ou BEHIND avec is_personal_record_target=True), la raison d'être de leur séparation. Bonus possible : un test de cohérence qui compare `time_status` aux champs dépréciés équivalents pendant toute la transition (les deux calculent la même vérité par deux chemins différents, un écart révèle un bug de migration).

**Étape 3 — migrer les consommateurs jusqu'à extinction des alertes obsolètes**, un par un, dans cet ordre (du plus simple au plus risqué) :
1. `expected_timing/plugin.py` + `tab_widget.py` (le plus simple, déjà refait plusieurs fois cette session)
2. `official_cockpit_hud/widgets/sector_times.py`
3. `official_cockpit_hud/widgets/delta_timer.py`
4. `gear_speed_hud/plugin.py`
Critère de fin d'étape concret et vérifiable par l'outillage (pas "je crois que plus personne ne lit ça") : zéro warning `DeprecationWarning` restant sur ces champs — recherche IDE-wide des `@deprecated` de l'étape 1, ou suite de tests lancée avec les deprecation warnings promus en erreur.

**Étape 4 — supprimer le code mort.** Une fois l'étape 3 à zéro alerte : retirer les champs dépréciés de `LapDeltaPacket`/`VehicleSensors`, retirer `sector_colors.py` (fusionné dans `resolve_target`), retirer les enums `SplitStatus`/`ExpectedStatus`/`LapColorStatus` (remplacés par `TimeTarget`).

## Points tranchés (plus rien d'ouvert bloquant pour commencer)

- `SectorEngine.session_split_best_s1/s2/s3` = paddock+moi-même (confirmé en lisant `update_session_bests`) → `WallOfFameEngine` calcule sa propre agrégation paddock-only, ne réutilise pas ces champs tels quels. Voir section Engine.
- `eps` n'est pas une constante domaine à `0.001` (aucun effet réel) : paramètre obligatoire de `resolve_target`/`resolve_is_personal_record_target`, fourni par la vue. Défaut recommandé **0.1s**, réglable dans le plugin cockpit comme `freeze_duration`. Voir section Résolution.
- Deltas de secteur/tour pas encore engagé : le domaine ne cache rien, calcule en continu comme aujourd'hui ; c'est la vue qui n'affiche rien tant que ce n'est pas `is_current`, sauf pendant la fenêtre de gel existante (`freeze_duration`, 3.5s par défaut). Voir section "Vue : quand cacher le delta".
