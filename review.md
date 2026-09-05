
# Review

## PRIORITY

j'ai demandé de ne pas mettre de priority, je veux un tableau trié, ca fait bugger les fonction de triage dans l'UI
```json 
{
  "simpad.builtin.race_engineer": {
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

[Makefile](Makefile)


## user_data

regrouper les data  utilisateur, et cache téléchargé

* [ref_laps](profiles/ref_laps)
* le fichier de configuration fusionné
* [sound](assets/sound)
* [isiMotor-RawUDP-Plugin](assets/plugins/isiMotor-RawUDP-Plugin)
* [models](assets/models)


## cripy code

Dict[str, Any],
getattr(
isinstance(
Any
Option
 __getitem__, get() et to_dict() 

supprimer le lerp dans les overlay c'est chiant visuelement ca donne une impression de molesse.