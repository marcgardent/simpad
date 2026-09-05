"""
SimPulse Qt — Parameter UI Widget Factory.
Creates Qt controls (QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox)
for declarative parameter descriptors (BoolParam, IntRangeParam, FloatRangeParam, ChoiceParam).
"""

from __future__ import annotations
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QWidget,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
)

from simpulse_sdk import (
    IParamDescriptor,
    BoolParam,
    IntRangeParam,
    FloatRangeParam,
    ChoiceParam,
    ParamScalarValue,
)


class ParamWidgetFactory:
    """Polymorphic widget factory for Qt UI parameter descriptors."""

    @staticmethod
    def create_widget(
        param: IParamDescriptor,
        parent: Optional[QWidget],
        current_value: Optional[ParamScalarValue],
        on_change: Callable[..., None],
    ) -> Optional[QWidget]:
        """Creates and configures the corresponding QWidget for a given parameter descriptor."""
        if isinstance(param, BoolParam):
            chk = QCheckBox(parent)
            val = param.default if current_value is None else current_value
            chk.setChecked(bool(val))
            chk.toggled.connect(on_change)
            return chk

        if isinstance(param, IntRangeParam):
            spin = QSpinBox(parent)
            spin.setRange(param.min_val, param.max_val)
            spin.setSingleStep(param.step)
            if param.unit:
                spin.setSuffix(f" {param.unit}")
            val = param.default if current_value is None else current_value
            spin.setValue(param.cast_and_validate(val))
            spin.valueChanged.connect(on_change)
            return spin

        if isinstance(param, FloatRangeParam):
            spin = QDoubleSpinBox(parent)
            spin.setRange(param.min_val, param.max_val)
            spin.setSingleStep(param.step)
            spin.setDecimals(1 if param.step >= 0.1 else 2)
            if param.unit:
                spin.setSuffix(f" {param.unit}")
            val = param.default if current_value is None else current_value
            spin.setValue(param.cast_and_validate(val))
            spin.valueChanged.connect(on_change)
            return spin

        if isinstance(param, ChoiceParam):
            combo = QComboBox(parent)
            if param.choices:
                for c in param.choices:
                    combo.addItem(c)
            val = str(param.default if current_value is None else current_value)
            idx = combo.findText(val)
            if idx != -1:
                combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(on_change)
            return combo

        return None


def create_param_widget(
    param: IParamDescriptor,
    parent: Optional[QWidget],
    current_value: Optional[ParamScalarValue],
    on_change: Callable[..., None],
) -> Optional[QWidget]:
    """Convenience helper to create a QWidget for a given parameter descriptor."""
    return ParamWidgetFactory.create_widget(param, parent, current_value, on_change)
