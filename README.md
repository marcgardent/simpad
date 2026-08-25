# SimPad Haptic Middleware

High-frequency real-time haptic synthesis middleware (50 Hz, 200 Hz, 1000 Hz) for racing simulators (Le Mans Ultimate, etc.) featuring a compiled node graph architecture.

---

## 📡 Telemetry Sensors Documentation `[0.0, 1.0]`

SimPad converts raw wheel velocities from simulator telemetry plugins into **4 dimensionless normalized sensors ranging from `0.0` to `1.0`**.

When cruising with full grip, all 4 sensors stay strictly at `0.0` (zero unwanted rumble). Vibration triggers proportionally only when physical tire slip occurs.

### 📐 Mathematical Formulation

For each wheel $i \in \{\text{FrontLeft}, \text{FrontRight}, \text{RearLeft}, \text{RearRight}\}$:

1. **Ground Velocity**: $v_{\text{ground}, i}$
2. **Longitudinal Patch Velocity**: $v_{\text{long\_patch}, i}$
3. **Lateral Patch Velocity**: $v_{\text{lat\_patch}, i}$

#### Dimensionless Relative Slip Ratios:
$$
\text{long\_slip}_i = \frac{v_{\text{long\_patch}, i} - v_{\text{ground}, i}}{\max(0.5, |v_{\text{ground}, i}|)}
$$

$$
\text{lat\_slip}_i = \min\left(1.0, \, \max\left(0.0, \, \frac{|v_{\text{lat\_patch}, i}|}{\max(0.5, v_{\text{ground}, i})}\right)\right)
$$

---

## 🏎️ The 4 Standardized Telemetry Sensors

### 1. 🔴 Over-Braking (Front Wheel Lock)
- **Formula**:
  $$
  \begin{aligned}
  \text{lock}_i &= \max\left(0.0, \min\left(1.0, -\text{long\_slip}_i\right)\right) \\
  \text{Over-Braking Sensor} &= \max\left(\text{lock}_{\text{FrontLeft}}, \text{lock}_{\text{FrontRight}}\right)
  \end{aligned}
  $$
- **Physics**: Under heavy braking, front wheel rotation speed drops below vehicle ground speed ($v_{\text{patch}} < v_{\text{ground}}$). `long_slip` becomes negative. The sensor measures the magnitude of front wheel lockup (0.0 = rolling freely, 1.0 = total wheel lockup).

---

### 2. 🟡 Over-Acceleration (Rear Wheel Spin)
- **Formula**:
  $$
  \begin{aligned}
  \text{spin}_i &= \max\left(0.0, \min\left(1.0, \text{long\_slip}_i\right)\right) \\
  \text{Over-Acceleration Sensor} &= \max\left(\text{spin}_{\text{RearLeft}}, \text{spin}_{\text{RearRight}}\right)
  \end{aligned}
  $$
- **Physics**: Under heavy acceleration out of corners, driven rear wheel rotation exceeds ground speed ($v_{\text{patch}} > v_{\text{ground}}$). `long_slip` is positive and measures rear wheel power spin intensity (0.0 = full traction, 1.0 = free spin).

---

### 3. 🔴 Oversteer (Rear Lateral Slip)
- **Formula**:
  $$
  \text{Oversteer Sensor} = \max\left(\text{lat\_slip}_{\text{RearLeft}}, \text{lat\_slip}_{\text{RearRight}}\right)
  $$
- **Physics**: Measures the lateral sliding velocity of the rear axle relative to ground speed. When the rear tail breaks away in a turn or drift, rear lateral slip ratio increases from 0.0 (clean grip line) to 1.0 (complete breakaway).

---

### 4. 🔵 Understeer (Front Lateral Scrub)
- **Formula**:
  $$
  \text{Understeer Sensor} = \max\left(\text{lat\_slip}_{\text{FrontLeft}}, \text{lat\_slip}_{\text{FrontRight}}\right)
  $$
- **Physics**: Measures the lateral sliding/scrubbing velocity of the front axle. When turning in aggressively and the front tires scrub wide, front lateral slip increases from 0.0 (crisp turn-in) to 1.0 (heavy front scrub).

---

### 5. ⚙️ Engine Regime (Sur-régime / Sous-régime & Shift Sweet Spots)
- **Formula & Normalization**:
  For engine RPM ratio $r = \frac{\text{RPM}}{\text{RPM}_{\max}}$:
  $$
  \begin{aligned}
  \text{Sur-régime (Over-rev / Upshift)} &= \text{clamp}\left(\frac{r - 0.90}{1.0 - 0.90}, \, 0.0, \, 1.0\right) \\
  \text{Sous-régime (Under-rev / Downshift)} &= \text{clamp}\left(\frac{0.45 - r}{0.45 - 0.20}, \, 0.0, \, 1.0\right)
  \end{aligned}
  $$
- **Physics & Shift Sweet Spots**:
  - 🏎️ **Upshift Sweet Spot**: Shift up right when the **Sur-régime** haptic signal reaches **`0.70` - `0.90`**. Upshifting at this exact window maximizes power output right before bouncing off the engine rev limiter (`1.0`).
  - 📉 **Downshift Sweet Spot**: Downshift under heavy braking when the **Sous-régime** signal enters **`0.30` - `0.60`**. Downshifting within this sweet spot keeps the engine landed cleanly in peak torque without causing rear compression lockup (rear wheel axle hop from excessive engine braking).

---

### 6. 🛞 Wheel Suspension Travel (Vibreurs / Curbs)
- **Formula**:
  $$
  \begin{aligned}
  \text{travel}_i &= \text{clamp}\left(\frac{\text{deflection}_i}{\text{max\_stroke}}, \, 0.0, \, 1.0\right) \\
  \text{Travel Left} &= \max\left(\text{travel}_{\text{FrontLeft}}, \text{travel}_{\text{RearLeft}}\right) \\
  \text{Travel Right} &= \max\left(\text{travel}_{\text{FrontRight}}, \text{travel}_{\text{RearRight}}\right)
  \end{aligned}
  $$
- **Physics**: Measures wheel vertical displacement / suspension compression relative to max suspension travel stroke. Riding over left curbs triggers `Travel Left`, while riding over right curbs triggers `Travel Right`.

---

## ⚡ High-Frequency Graph Synthesizer Engine

The **GraphCompiler** JIT-compiles visual node graphs into standalone Python bytecode functions executed inside a dedicated thread running at **50 Hz, 200 Hz, or 1000 Hz**.

```bash
uv run python main.py
```

---

## 🤖 AI Graph Preset Generation & JSON Specification

SimPad allows Generative AI models (ChatGPT, Claude, Gemini, DeepSeek) to generate custom haptic graphs in standard JSON format. AI-generated presets can be loaded directly using the **Import JSON** button in the UI.

### 📐 Graph JSON Format

```json
{
  "nodes": {
    "node_id_1": {
      "type": "transform",
      "in_attr": "attr_in_tf_1",
      "out_attr": "attr_out_tf_1",
      "thresh": 0.10,
      "gain": 1.5,
      "gamma": 0.8,
      "pos": [260.0, 40.0]
    },
    "node_id_2": {
      "type": "shape",
      "in_attr": "attr_in_shape_1",
      "in_on": "attr_in_shape_1_on",
      "in_off": "attr_in_shape_1_off",
      "out_attr": "attr_out_shape_1",
      "shape": "Square (Pulsed)",
      "on_ms": 15.0,
      "off_ms": 25.0,
      "pos": [460.0, 40.0]
    }
  },
  "links": [
    ["attr_out_abs", "attr_in_tf_1"],
    ["attr_out_tf_1", "attr_in_shape_1"],
    ["attr_out_shape_1", "attr_in_high"]
  ]
}
```

---

### 📌 Registered Pins Reference

#### 1. Telemetry Sensor Output Pins (Source Pins)
- **Over-Braking**: `attr_out_abs` (Max), `attr_out_abs_l` (Left), `attr_out_abs_r` (Right)
- **Over-Acceleration**: `attr_out_tc` (Max), `attr_out_tc_l` (Left), `attr_out_tc_r` (Right)
- **Oversteer**: `attr_out_over` (Max), `attr_out_over_l` (Left), `attr_out_over_r` (Right)
- **Understeer**: `attr_out_und` (Max), `attr_out_und_l` (Left), `attr_out_und_r` (Right)
- **Engine Regime**: `attr_out_over_rev` (Sur-régime / Upshift), `attr_out_under_rev` (Sous-régime / Downshift), `attr_out_rpm` (RPM Ratio)
- **Wheel Travel**: `attr_out_travel` (Max), `attr_out_travel_l` (Left), `attr_out_travel_r` (Right), `attr_out_travel_fl`, `attr_out_travel_fr`, `attr_out_travel_rl`, `attr_out_travel_rr`

#### 2. XInput Motor Input Pins (Destination Pins - Red Summing Multi-Ports)
- **Low Freq Rumble (Left)**: `attr_in_low`
- **High Freq Buzz (Right)**: `attr_in_high`

---

### 🧩 Node Types & Parameters

| Node Type | Description | Key Parameters / Pins |
| :--- | :--- | :--- |
| `sensor_over_braking` | Over-Braking telemetry sensor input | Outputs: `attr_out_abs` (Max), `attr_out_abs_l` (Left), `attr_out_abs_r` (Right) |
| `sensor_over_accel` | Over-Acceleration telemetry sensor input | Outputs: `attr_out_tc` (Max), `attr_out_tc_l` (Left), `attr_out_tc_r` (Right) |
| `sensor_oversteer` | Oversteer telemetry sensor input | Outputs: `attr_out_over` (Max), `attr_out_over_l` (Left), `attr_out_over_r` (Right) |
| `sensor_understeer` | Understeer telemetry sensor input | Outputs: `attr_out_und` (Max), `attr_out_und_l` (Left), `attr_out_und_r` (Right) |
| `sensor_engine_regime` | Engine Regime telemetry sensor input | Outputs: `attr_out_over_rev` (Sur-régime), `attr_out_under_rev` (Sous-régime), `attr_out_rpm` |
| `sensor_wheel_travel` | Wheel Travel telemetry sensor input | Outputs: `attr_out_travel` (Max), `attr_out_travel_l` (Left), `attr_out_travel_r` (Right), `attr_out_travel_fl`, `attr_out_travel_fr`, `attr_out_travel_rl`, `attr_out_travel_rr` |
| `constant` | Normalized scalar `[0.0, 1.0]` | `"val"` (float) |
| `float_constant` | Raw float value (ms/scalar) | `"val"` (float) |
| `multiply` | Multiplies 2 inputs | `"in_a"`, `"in_b"`, `"out_attr"` |
| `array_multiply` | Multiplies N incoming signals | `"in_attr"`, `"out_attr"` |
| `normalize` | Normalizes `[min, max]` to `[0, 1]` | `"min"`, `"max"`, `"clamp"`, `"in_attr"`, `"out_attr"` |
| `math` | Binary arithmetic (+, -, *, /, min, max) | `"op"` ("Add (+)", "Multiply (*)", "Subtract (-)", "Divide (/)", "Min (min)", "Max (max)") |
| `transform` | Threshold, Gain, Gamma curve | `"thresh"` (0.0-0.5), `"gain"` (0.0-2.0), `"gamma"` (0.2-3.0) |
| `shape` | Waveform modulation | `"shape"` ("Square (Pulsed)", "Sawtooth (Scrub)", "Sine (Smooth)", "Burst (Impact)"), `"on_ms"`, `"off_ms"` |

---

### 💡 AI System Prompt for Preset Generation

Copy and paste the prompt below into ChatGPT / Claude / Gemini to generate custom SimPad haptic presets:

> *"You are an expert SimPad haptic preset designer. Generate a valid SimPad JSON graph for [insert vehicle/driving style, e.g. Rally Gravel ABS & Oversteer emphasis]. Use valid pins `attr_out_abs`, `attr_out_tc`, `attr_out_over`, `attr_out_und` (and L/R variants) and connect to `attr_in_low` or `attr_in_high`. Output only valid raw JSON."*
