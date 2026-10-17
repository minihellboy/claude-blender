---
name: blender-turntable
description: Create a 360-degree turntable animation video of an object in the Blender scene. Use when the user wants to show a model from all sides (e.g. "make a turntable of the dragon", "spin the product").
argument-hint: <object-name> [seconds]
---

# Turntable animation

Create a 360° turntable of the object in `$ARGUMENTS`
(format: `<object_name> [seconds]`, default 4 seconds at 24 fps).

## Procedure

1. **Verify**: `blender_get_object` for the subject's location/dimensions.
2. **Checkpoint**: `blender_checkpoint "turntable rig"`.
3. **Rig** (rotate a pivot, not the object — keeps the object's own transform
   clean): add an `empty` at the subject's center; frame the camera with
   `blender_frame_camera` (elevation ~15°, margin 1.25); then parent the
   camera to the empty with `blender_organize` action=parent.
4. **Animate the pivot**: frames = seconds x 24. `blender_set_frame_range`
   1 to frames. Keyframe the empty's Z rotation with
   `interpolation="LINEAR"`: 0 at frame 1, 2π at the last frame. LINEAR
   keeps the spin constant-speed - the default Bezier easing makes a looping
   turntable stutter at the seam.
5. **Motion draft**: `blender_render_job_start` with `frame_step` 4,
   640x360, EEVEE_NEXT, then `blender_render_job_status` with
   `wait_seconds` 120. The returned contact sheet spans the whole orbit —
   verify the subject stays framed all the way around. Off-center subjects
   orbit out of frame; re-center the empty if so.
6. **Render**: `blender_render_job_start` at the full frame rate,
   1280x720 — EEVEE_NEXT for speed (CYCLES only if the user asks for
   quality). It runs in the background: tell the user the job_id and ETA,
   long-poll `blender_render_job_status` (`wait_seconds` up to 600) until
   `completed`, and `blender_render_job_cancel` if a preview frame shows a
   problem. Inspect the final contact sheet: consistent framing? lighting
   stable through the rotation?
7. Report the video path and the contact sheet. Offer a Cycles re-render at
   higher resolution if the user wants final quality.
