---
name: blender-iterate
description: Iteratively build or refine a Blender scene toward a visual goal using render-critique loops. Use when the user describes a desired look ("make it moodier", "build a cozy campfire scene") rather than a single concrete edit.
argument-hint: <visual goal>
---

# Blender visual iteration loop

Work toward the visual goal in `$ARGUMENTS` by rendering, critiquing your own
image, and adjusting — like a sculptor stepping back after every pass.

## Loop (max 4 rounds before checking in with the user)

1. **Inspect**: `blender_get_scene` (detailed) — know every object, light, and
   camera before touching anything.
2. **Checkpoint**: `blender_checkpoint` with a label naming the round
   (e.g. "iterate round 2"). If a round makes things worse, `blender_undo`
   back to the checkpoint instead of stacking corrections on a mistake.
3. **Act**: make the changes for this round with dedicated tools
   (`blender_add_object`, `blender_create_material`, `blender_modifier`,
   `blender_frame_camera`, ...). Use `blender_execute` only for what they
   can't do.
4. **Draft render**: `blender_render` at 640x360, `BLENDER_EEVEE_NEXT`,
   32 samples. Never draft at full quality — a draft answers questions,
   it isn't the deliverable.
5. **Critique the returned image against the goal.** Be specific and harsh,
   in this order:
   - Composition: is the subject framed and unobstructed? Horizon level?
   - Silhouette/shapes: do the forms read as what they're meant to be?
   - Lighting: key direction, contrast, shadows going somewhere sensible?
   - Materials: do surfaces read correctly (metal looks metal, glass glass)?
   - Mood: does it match the goal's adjectives?
   Write the critique down in one or two sentences before deciding the next
   round's changes.
6. Repeat until the draft matches the goal or 4 rounds are spent.

## Finish

- Final render: `blender_render` with CYCLES, 1920x1080, 128+ samples.
- Offer `blender_save` - renders don't persist the scene; only saving does.
- Report what changed each round and show the final image path.
- If 4 rounds weren't enough, show the best draft, list what still falls
  short, and ask the user how to proceed.
