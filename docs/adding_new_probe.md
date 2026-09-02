# Guide d'Intégration d'une Nouvelle Sonde (Probe / Sensor Node) dans SimPad

Ce document décrit pas à pas la méthodologie et l'architecture pour ajouter une nouvelle sonde (*probe sensor node*) dans l'écosystème SimPad (middleware haptique, compilateur JIT de nœuds graphiques, boîte à outils et interface Dear PyGui).

---

## Architecture des Sondes dans SimPad

Dans SimPad, une sonde (*Probe*) est un nœud d'entrée de télémétrie (*Input Node*) qui expose des données physiques normalisées sans dimension (clampées entre `0.0` et `1.0`).

La télémétrie suit la chaîne suivante :
```
[Télémétrie LMU / SIM] 
        │ (Paquet UDP)
        ▼
 [LMUParser / TelemetryData]
        │
        ▼
 [VehicleSensors] ── (Calculs normalisés & clampés entre 0.0 et 1.0)
        │
        ▼
 [HapticSynthesizerEngine] ── (Stockage thread-safe de la télémétrie)
        │
        ▼
 [GraphCompiler / NodeFactory] ── (Génération & Compilation JIT du code Python)
        │
        ▼
 [NodeUIFactory / Node Toolbox / Monitor (Dear PyGui)]
        │ ├── Boîte à outils (Node Toolbox) pour ajouter le nœud dans le canvas
        │ ├── Contrôle manuel Live Test (Sliders & Impulsion)
        │ └── Graphique dynamique en temps réel dans l'onglet Monitor
```

---

## Procédure d'Ajout d'une Nouvelle Probe

Pour intégrer une sonde nommée **`GripFract`** (représentant la fraction d'adhérence restante des pneumatiques clampée entre `0.0` et `1.0`), suivez les 7 étapes ci-dessous.

---

### Étape 1 : Domaine Télémétrie (`src/telemetry/sensors.py`)

1. Ajoutez les champs requis dans la dataclass `VehicleSensors`.
2. Calculez les valeurs normalisées dans `from_wheel_velocities(...)` et appliquez un clamp strict `[0.0, 1.0]`.
3. Ajoutez les propriétés d'intensité globales, côté gauche (*Left*), et côté droit (*Right*).

**Exemple :**
```python
@dataclass
class VehicleSensors:
    # Champs pour les 4 roues
    front_left_grip: float = 1.0
    front_right_grip: float = 1.0
    rear_left_grip: float = 1.0
    rear_right_grip: float = 1.0

    @property
    def grip_intensity(self) -> float:
        """Adhérence globale unifiée 4 roues (minimum clampé [0.0, 1.0])."""
        return min(self.front_left_grip, self.front_right_grip, self.rear_left_grip, self.rear_right_grip)

    @property
    def grip_left(self) -> float:
        """Adhérence côté Gauche (minimum FL, RL clampé [0.0, 1.0])."""
        return min(self.front_left_grip, self.rear_left_grip)

    @property
    def grip_right(self) -> float:
        """Adhérence côté Droit (minimum FR, RR clampé [0.0, 1.0])."""
        return min(self.front_right_grip, self.rear_right_grip)
```

---

### Étape 2 : Définition du Nœud Graphique (`src/nodes/sensor.py`)

Créez la classe du nœud d'entrée héritant de `BaseNode`. Spécifiez :
- `node_type` : Identifiant unique (ex: `"sensor_grip_fract"`).
- `display_name` : Nom affiché dans le menu contextuel et l'éditeur (ex: `"Input: Grip Fraction"`).
- `generate_code()` : Code Python généré lors de la compilation du graphe.

**Exemple :**
```python
class GripFractSensorNode(BaseNode):
    """Nœud d'entrée capteur pour la fraction d'adhérence des pneus (0.0 à 1.0)."""

    @property
    def node_type(self) -> str:
        return "sensor_grip_fract"

    @property
    def display_name(self) -> str:
        return "Input: Grip Fraction"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_max = ninfo.get("out_attr", "attr_out_grip")
        out_l = ninfo.get("out_l", "attr_out_grip_l")
        out_r = ninfo.get("out_r", "attr_out_grip_r")
        lines = [
            f"    # Sensor Node: Grip Fraction ({ntag})",
            "    val_map['attr_out_grip'] = grip_val",
            "    val_map['attr_out_grip_l'] = grip_l",
            "    val_map['attr_out_grip_r'] = grip_r",
        ]
        if out_max != "attr_out_grip": lines.append(f"    val_map['{out_max}'] = grip_val")
        if out_l != "attr_out_grip_l": lines.append(f"    val_map['{out_l}'] = grip_l")
        if out_r != "attr_out_grip_r": lines.append(f"    val_map['{out_r}'] = grip_r")
        lines.append("")
        return lines
```

Enregistrez la classe dans `src/nodes/factory.py` et exportez-la dans `src/nodes/__init__.py`.

---

### Étape 3 : Compilateur & Synthesizer (`src/core/compiler.py` & `src/core/synthesizer.py`)

1. **Dans `src/core/compiler.py`** :
   - Extrayez la nouvelle variable dans l'entête du code généré :
     ```python
     grip_val = min(1.0, max(0.0, telemetry.get('grip', 0.0)))
     grip_l   = min(1.0, max(0.0, telemetry.get('grip_l', grip_val)))
     grip_r   = min(1.0, max(0.0, telemetry.get('grip_r', grip_val)))
     ```
   - Inscrivez les attributs par défaut dans `val_map` :
     ```python
     'attr_out_grip': grip_val,
     'attr_out_grip_l': grip_l,
     'attr_out_grip_r': grip_r,
     ```

2. **Dans `src/core/synthesizer.py`** :
   - Mettez à jour `update_telemetry()` pour accepter `grip_val`, `grip_l`, `grip_r`.

---

### Étape 4 : Interface Graphique UI & Boîte à Outils Toolbox

Pour permettre l'instanciation visuelle du nœud et sa sauvegarde/restauration :

1. **Dans `src/gui/node_editor/node_factory_ui.py`** :
   - Créez la méthode de construction UI : `add_node_sensor_grip(...)`.
   ```python
   def add_node_sensor_grip(self, custom_nodes: Dict[str, dict], recompile_cb: Callable[[], None], pos=(30.0, 700.0)) -> str:
       pos_f = self.get_next_spawn_pos(custom_nodes, pos)
       nid = self.get_next_nid(custom_nodes)
       node_tag = f"dynamic_node_sensor_grip_{nid}"
       out_max_tag = f"attr_out_dyn_grip_{nid}"
       out_l_tag = f"attr_out_dyn_grip_l_{nid}"
       out_r_tag = f"attr_out_dyn_grip_r_{nid}"

       with dpg.node(label=f"Input: Grip Fraction #{nid}", tag=node_tag, parent="node_editor_canvas", pos=pos_f):
           with dpg.node_attribute(label="Grip Fraction (Unified)", attribute_type=dpg.mvNode_Attr_Output, tag=out_max_tag):
               dpg.add_text("Grip Fraction (Unified)", color=[0, 255, 180, 255])
           with dpg.node_attribute(label="Grip Fraction (Left)", attribute_type=dpg.mvNode_Attr_Output, tag=out_l_tag):
               dpg.add_text("Grip Fraction (Left)", color=[0, 255, 180, 255])
           with dpg.node_attribute(label="Grip Fraction (Right)", attribute_type=dpg.mvNode_Attr_Output, tag=out_r_tag):
               dpg.add_text("Grip Fraction (Right)", color=[0, 255, 180, 255])

       for pin in [out_max_tag, out_l_tag, out_r_tag]:
           self.apply_pin_theme(pin, "normalized")

       custom_nodes[node_tag] = {
           "type": "sensor_grip_fract",
           "out_attr": out_max_tag,
           "out_l": out_l_tag,
           "out_r": out_r_tag,
       }
       recompile_cb()
       return node_tag
   ```

2. **Dans `src/gui/node_editor/editor_tab.py`** :
   - Ajoutez le bouton d'ajout dans la section `Telemetry Sensors` de la boîte à outils (*Toolbox*) :
   ```python
   dpg.add_button(label="+ Grip Fraction Sensor", width=-1, callback=lambda: self._add_node_sensor_grip())
   ```
   - Ajoutez la méthode relai `_add_node_sensor_grip(...)`.

3. **Dans `src/gui/node_editor/graph_serializer.py`** :
   - Déclarez l'équivalence dans `import_graph_from_dict` pour permettre la désérialisation depuis les fichiers de profil JSON :
   ```python
   elif ntype == "sensor_grip_fract":
       new_ntag = editor_tab._add_node_sensor_grip(pos=pos)
   ```

---

### Étape 5 : Intégration pour Test Live dans le Sidebar (`src/gui/node_editor/sidebar_control.py`)

Pour tester la nouvelle sonde manuellement en temps réel dans l'éditeur de nœuds :
1. Ajoutez les sliders de test dans le panneau latéral (`test_sensor_grip_l` et `test_sensor_grip_r`), avec la valeur par défaut **`0.0`**.
2. Mettez à jour `on_test_sensor_change` et `reset_test_sensors` pour réinitialiser les sliders à **`0.0`**.

```python
dpg.add_text("Grip Fraction", color=[0, 255, 180, 255])
with dpg.group(horizontal=True):
    dpg.add_slider_float(label="L", tag="test_sensor_grip_l", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=...)
    dpg.add_slider_float(label="R", tag="test_sensor_grip_r", default_value=0.0, min_value=0.0, max_value=1.0, format="%.2f", width=120, callback=...)
```

---

### Étape 6 : Intégration et Affichage dans le Monitor (`src/gui/dpg_app.py`)

Pour visualiser la courbe du capteur en direct dans l'onglet **Monitor** (Dear PyGui Plot) :
1. **Initialisation des tampons de données de télémétrie** :
   ```python
   self._d_grip = deque([0.0] * HISTORY, maxlen=HISTORY)
   ```
2. **Configuration de la série temporelle dans le plot** :
   ```python
   dpg.add_line_series([], [], label="Grip Fraction", tag="mon_series_grip")
   ```
3. **Mise à jour des séries dans la boucle d'affichage (Tick rendering)** :
   ```python
   self._d_grip.append(sensors.grip_intensity)
   dpg.set_value("mon_series_grip", [list(self._t), list(self._d_grip)])
   ```

---

### Étape 7 : Validation & Tests Automated / Manuels

1. Exécutez les tests unitaires :
   ```bash
   .venv\Scripts\python.exe -m unittest discover -s tests
   ```
2. Lancez l'application (`python main.py` ou `dpg_app.py`).
3. Dans la boîte à outils (*Node Toolbox*), cliquez sur **`+ Grip Fraction Sensor`** pour ajouter le nœud dans le canvas.
4. Manipulez les sliders live dans le panneau latéral (Sidebar) et observez le comportement haptique ainsi que le tracé dans le Monitor.
