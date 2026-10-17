---
name: blender-studio-shot
description: Produce a studio-quality product shot of an object in the Blender scene - three-point lighting, camera framing, backdrop, and a final Cycles render. Use when the user wants a clean presentation image of a model.
argument-hint: [object-name]
---

# Studio product shot

Produce a studio-quality hero shot of the object named in `$ARGUMENTS`
(if empty: the most prominent mesh in the scene — check `blender_get_scene`).

## Procedure

1. **Verify the subject**: `blender_get_object` for its location and
   dimensions. Everything below scales from those dimensions (call the
   largest dimension D). A quick `blender_render_views` shows its best side
   before you commit to a camera angle.
2. **Checkpoint**: `blender_checkpoint "studio shot setup"`.
3. **Backdrop**: add a large plane (~10x D) under the subject; give it a
   smooth curved sweep behind the subject if the look calls for an infinity
   cove (`blender_execute` with a curved plane or a big soft-material plane
   is fine). Neutral material: roughness 0.9, color light gray.
4. **Three-point lighting**, scaled to D and the subject's height — each is
   one `blender_add_object` call with `energy`, `color`, and `size`:
   - Key: `area`, ~45° front-left, elevated, size ≈ D, warm color,
     energy ~800 (soft shadows come from size).
   - Fill: `area`, front-right, half the key's energy, size ≈ 1.5×D.
   - Rim: behind/above the subject, cool color, to separate it from the
     backdrop.
5. **Frame**: `blender_frame_camera` targeting the subject —
   `azimuth_deg` ~30-45, `elevation_deg` ~15-25, `lens` 85, `margin` 1.2.
6. **Draft loop** (2-3 rounds): `blender_render` at 640x360, CYCLES,
   16 samples. Critique: subject centered with breathing room? Key shadows
   soft and falling away from camera? Rim visible on the subject's edge?
   Backdrop seamless (no visible edges)? Adjust lights/camera and re-draft.
7. **Final**: `blender_render` CYCLES, 1920x1080, 256 samples. If the user
   gave an output path, render straight to it.
   `blender_save` / `blender_export` ask the user before replacing a
   different existing file — if they decline, ask for a new path.
8. Report the light setup you landed on (positions/powers) so it's
   reproducible, and show the final render.
