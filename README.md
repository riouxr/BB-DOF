# BB DOF

Real-time depth-of-field visualiser for Blender.  
Found in **Properties → Render → BB DOF**.

![Version](https://img.shields.io/badge/version-1.3.3-blue) ![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange)

---

## What it does

Three coloured planes show your depth-of-field range directly in the viewport:

- 🔴 **Red** — near out-of-focus limit
- ⚪ **White** — focal plane
- 🔵 **Blue** — far out-of-focus limit

Planes are visible in all shading modes and hide automatically when looking through the camera.

---

## Buttons

| Button | What it does |
|--------|-------------|
| **Colors** | Applies a red→green→blue material override so every object is tinted by how far it is from focus |
| **Clipping** | Sets the camera's clip start/end to exactly the DoF near/far limits |
| **Planes** | Toggles the coloured plane overlays on/off |

Colors and Clipping are mutually exclusive. Planes are independent.

---

## Installation

1. Download `bb_dof.zip`
2. Drag and drop the zip into the Blender viewport
3. Find the panel at **Properties → Render → BB DOF**

---

## Usage

1. Select your target camera from the list
2. Adjust **Focus** and **F-stop** sliders
3. Toggle **Colors**, **Clipping**, or **Planes** as needed
