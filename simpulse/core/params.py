"""
SimPulse Declarative Configurable Parameters for Roles & Subplugins.
Re-exported from simpulse_sdk for single source of truth, with Qt widget factory integration.
"""
from __future__ import annotations
from typing import Optional, Callable

from simpulse_sdk import (
    IParamDescriptor,
    ConfigParam,
    PluginParam,
    RoleParam,
    SubpluginParam,
    ParamDescriptor,
    BoolParam,
    IntRangeParam,
    FloatRangeParam,
    ChoiceParam,
    ParamScalarValue,
)
from simpulse.ui.param_widget_factory import ParamWidgetFactory, create_param_widget

# Attach create_widget to ConfigParam for backward compatibility in Qt environment
def _config_param_create_widget(
    self: ConfigParam,
    parent: Optional[object] = None,
    current_value: Optional[ParamScalarValue] = None,
    on_change: Optional[Callable[..., None]] = None,
):
    from PySide6.QtWidgets import QWidget
    parent_w = parent if isinstance(parent, QWidget) else None
    cb = on_change if on_change is not None else (lambda *_: None)
    return ParamWidgetFactory.create_widget(self, parent_w, current_value, cb)

setattr(ConfigParam, "create_widget", _config_param_create_widget)

__all__ = [
    "IParamDescriptor",
    "ConfigParam",
    "PluginParam",
    "RoleParam",
    "SubpluginParam",
    "ParamDescriptor",
    "BoolParam",
    "IntRangeParam",
    "FloatRangeParam",
    "ChoiceParam",
    "ParamScalarValue",
    "ParamWidgetFactory",
    "create_param_widget",
]
