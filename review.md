
# Review

## PRIORITY

j'ai demandé de ne pas mettre de priority, je veux un tableau trié, ca fait bugger les fonction de triage dans l'UI
```json 
{
  "simpulse.builtin.race_engineer": {
    "master_enabled": true,
    "muted": false,
    "subplugin_configs": {
      "pitlane_spotter": {
        "enabled": false,
        "priority": 110
      }
    }
  }
}
```
## fragmentation

A fusionner dans config.json verifier le binding de config.json completement ignoré

[game_plugin_settings.json](config/game_plugin_settings.json)
[config.json](config.json)
[config_qt.json](config_qt.json)
[engineer_config.json](engineer_config.json)


## French drift

- [x] [Makefile](Makefile) (translated to English and added `make french-drift` target)


## user_data

regrouper les data  utilisateur, et cache téléchargé

* [ref_laps](profiles/ref_laps)
* le fichier de configuration fusionné
* [sound](assets/sound)
* [isiMotor-RawUDP-Plugin](assets/plugins/isiMotor-RawUDP-Plugin)
* [models](assets/models)


## overlay

supprimer le lerp dans les overlay c'est chiant visuelement ca donne une impression de molesse.

## cripy code

Dict[str, Any] :
 - typer et pas utiliser d'autre type générique
 - Si il faut manipuler une abstraction, et bien tu créer le type.

getattr(
 - ca degage sans ambiguité

 - isinstance():
 - acceptable dans une Factory, dans le reste du code, on utilise le polymorphisme, on créer un abstract  

Any:
  - typer et pas utiliser d'autre type générique
  - Si il faut manipuler une abstraction, et bien tu créer le type.

Option en argument :
  - soit suppresion de l'appel quand la data est pas disponible  
  - soit tu découpes en deux methodes un avec la data une sans la data

 __getitem__, get() et to_dict() 
def get_instance(cls) -> "TelemetryStateStore":


if TYPE_CHECKING:
    from ..models.context import EngineerContext



# Layout 

* Plugin Inspector à droite
* Race engineer > afficher la liste complete des audios
* Changer le titre de l'ui ! SimPulse
* Faire un mode IDLE de l'UI quand le jeu video est en Live, overlay actif. Pour consommer moins de ressource.



# Exception AST
couper les couille au exception silencieuse ;  catch:pass