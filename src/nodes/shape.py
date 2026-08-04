"""
SimPad Nodes — Waveform Shape Node.
"""

from typing import Dict, List
from src.nodes.base import BaseNode


class ShapeNode(BaseNode):
    """Generates time-modulated haptic pulse waveforms (Square, Sawtooth, Sine, Burst)."""

    @property
    def node_type(self) -> str:
        return "shape"

    @property
    def display_name(self) -> str:
        return "Waveform Shape"

    def generate_code(self, ntag: str, ninfo: dict, in_to_outs: Dict[str, List[str]]) -> List[str]:
        out_attr = ninfo.get("out_attr")
        shape_choice = ninfo.get("shape", "Square (Pulsed)")
        base_freq = float(ninfo.get("freq", 20.0))
        base_duty = float(ninfo.get("duty", 0.40))
        in_attr = ninfo.get("in_attr")
        in_freq = ninfo.get("in_freq")

        lines = [
            f"    # Waveform Shape Node {ntag} ({shape_choice})",
            f"    in_src_{ntag} = {in_to_outs.get(in_attr, [None])}",
            f"    in_freq_src_{ntag} = {in_to_outs.get(in_freq, [None])}",
            f"    vin_{ntag} = val_map.get(in_src_{ntag}[0], 0.0) if in_src_{ntag} else 0.0",
            f"    freq_{ntag} = float(val_map.get(in_freq_src_{ntag}[0], {base_freq})) if in_freq_src_{ntag} else {base_freq}",
            f"    freq_{ntag} = max(0.1, freq_{ntag})",
            f"    duty_{ntag} = max(0.01, min(1.0, {base_duty:.4f}))",
            f"    if vin_{ntag} > 0.01:",
            f"        period_s_{ntag} = 1.0 / freq_{ntag}",
            f"        phase_{ntag} = (t % period_s_{ntag}) / period_s_{ntag}",
            f"        if phase_{ntag} <= duty_{ntag}:",
            f"            phi_{ntag} = phase_{ntag} / max(0.001, duty_{ntag})"
        ]

        if "Square" in shape_choice:
            lines.append(f"            mod_{ntag} = 1.0")
        elif "Sawtooth" in shape_choice:
            lines.append(f"            mod_{ntag} = phi_{ntag}")
        elif "Sine" in shape_choice:
            lines.append(f"            mod_{ntag} = 0.5 * (1.0 + math.sin(2.0 * math.pi * phi_{ntag} - math.pi / 2.0))")
        elif "Burst" in shape_choice:
            lines.append(f"            mod_{ntag} = math.exp(-4.0 * phi_{ntag})")
        else:
            lines.append(f"            mod_{ntag} = 1.0")

        lines.extend([
            f"        else:",
            f"            mod_{ntag} = 0.0",
            f"        res_{ntag} = min(1.0, max(0.0, vin_{ntag} * mod_{ntag}))",
            f"    else:",
            f"        res_{ntag} = 0.0",
            f"    val_map['{out_attr}'] = res_{ntag}",
            ""
        ])
        return lines
