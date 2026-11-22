# Product animations

Pre-rendered, looping 3D clips for the product page, made with Blender (EEVEE) from the CAD
export in `mech/out/`.

```
mech/assembly.py N  ──>  mech/out/assembly_N.glb  ──>  Blender: studio.py + shots/SHOT.py
                                                          │  PNG frames (site/anim/build/)
                                                          ▼
                                                   ffmpeg: site/media/SHOT.{mp4,webm,jpg}
```

## Running

```sh
uv run site/anim/render.py SHOT --stills 6       # 6 draft stills + sheet.png in build/SHOT/draft/stills/
uv run site/anim/render.py SHOT --frames 1 90    # just these frames
uv run site/anim/render.py SHOT                  # whole loop, draft (every 2nd frame, 15 fps): frames in build/SHOT/draft/frames/, mp4 in draft/
uv run site/anim/render.py SHOT -q preview       # whole loop, 960x540, mp4 in build/
uv run site/anim/render.py SHOT -q final         # 2560x1440: site/media/SHOT.{mp4,webm,jpg}
uv run site/anim/render.py SHOT -q preview -j 2  # two Blenders side by side, every 2nd frame each
```

### Rendering elsewhere (render farm, rented GPU)

```sh
uv run site/anim/render.py SHOT -q final --no-render    # only build/SHOT/final/SHOT.blend, ~6 s
# render that .blend anywhere (frames 1..N); put the frames in build/SHOT/final/frames/####.png
uv run site/anim/render.py SHOT -q final --encode-only  # encode them into site/media/
uv run site/anim/render.py SHOT -q final --encode-only --from renders/SHOT-*.zip  # straight from the farm's zips
```

The saved .blend is self-contained: everything is packed, and the frame range, step,
resolution, samples, compositor and output path (`//frames/####`) are set, so it renders
with plain `blender -b SHOT.blend -a`, with no scripts. The farm must run Blender 5.3.
`--encode-only` assumes 30 fps; pass `--fps` for other rates.

### Aspect ratios

Each shot is rendered once, at 21:9 (`--aspect`). The camera has a fixed vertical field of
view (`sensor_fit = 'VERTICAL'`), so a centre crop of that render is exactly what a 16:9 render
would be. `--exports 21x9,16x9` (the default) writes `SHOT.*` (16:9) and `SHOT-21x9.*` from the
same frames. The vignette is added per export by ffmpeg, not in the compositor, so each crop
gets its own. Contact sheets show yellow lines where the 16:9 crop falls: keep the important
parts of a shot inside them. The page (`site/index.html`) only uses the 21:9 export
(`media/SHOT-21x9.{webm,mp4,jpg}`) and crops it with `object-fit: cover`: narrower screens lose
the sides, so a phone in portrait sees only the middle of the frame. Keep the product centred.
Draft clips go to `site/media/` by hand (`cp build/SHOT/draft/SHOT-21x9.mp4 ../media/`, plus a
first-frame poster); a final render overwrites them.

## Files

- `render.py`: host-side driver (runs with uv): starts Blender, then the contact sheet or ffmpeg.
- `main.py`: Blender-side entry: builds the shot, saves the .blend, renders frames.
- `studio.py`: the shared look and helpers.
  - `Studio`: frame range, `unit()` (import a GLB), `stage()` (world, lights, floor),
    `camera_rig()`, then `orbit()` or `camera_path()` (or `pose()` + `loop_camera()`),
    `finish()` (render settings + compositor).
  - `Unit`: one imported assembly. `modules[k]` (module 1 is the right-hand end, with the Pico),
    `find()`/`one()` by part name, `center()`, `restyle()`, `set_plates(finish)`,
    `press(k, down, up)`, `led(k, frame, color)`.
- `shots/*.py`: one file per clip, each with `build(s)`.

## The look

- Near-black world. Lights: a soft warm key from above, a faint cool fill, and two thin rim
  strips behind the product (blue left, magenta right). They are parented to the camera rig,
  so they turn with the camera and the rims never reflect straight into the lens.
- Floor: near-black, with a sand-blasted-stone micro texture (blotchy roughness plus a fine
  bump grain). Its reflection fades out about 30 cm from the centre. Never let its Specular
  IOR Level reach 0: EEVEE then renders red/green garbage.
- Compositor: Bloom (threshold 1.2, so only LEDs and real highlights glow), then a wide, faint
  Fog Glow, then a soft vignette. Depth of field on the camera, f/4 by default.
- Colour: AgX, Medium High Contrast.
- LEDs: an emissive lens material per module plus a small point light above it, so the colour
  spills onto the plate. Keyframed with constant interpolation (on/off).
- Plates: `ACRYLIC` in studio.py: `clear`, `black`, `white_matte`, `pink`.
  `clear` is transmission and needs raytracing even in draft: set `s.raytrace = True` in the shot.

### Things that hang the Intel iGPU (VK_ERROR_DEVICE_LOST, `GPU HANG` in the kernel log)

- Alpha transparency (Principled `Alpha` < 1) anywhere in view. Use transmission + raytracing.
- Subsurface scattering on small parts seen close up (the LED spacers did it), and on the
  plates in the colours shot's wipe material (frames with a seam crossing a subsurfaced finish
  hung every time). A single plate finish with subsurface has been fine.
- Even without any of these, a long run in one Blender process sometimes hangs. Render long
  loops in batches of a few frames per process and re-render white frames.
- Scaling a parent to 0 to hide it while it has lights under it. Park things under the floor
  instead (see shots/expandable.py).
A hung frame comes out white or garbled, and Blender usually crashes on the next one.

## Shots

- `pedals.py`: 1, Your MIDI pedals. Momentary (red) and latching (green) switches.
- `exploded.py`: 2, Open Hardware. Walls come apart along their pins, then the layers lift top
  first (`LAYERS`, lifts growing with height so nothing collides); camera tours the boards.
- `expandable.py`: 3, Expandable. Bare boards; board 2 then six copies glide in and get cabled.
- `colors.py`: 4, Customizable. Hovering, turning unit; glowing seams wipe plate finish, wall
  colour and LED colours together (`LOOKS`).

## Loops

A clip is frames 1..N, and frame N+1 has to equal frame 1. An orbit from `a` to `a + 360`
keyed at frame 1 and N+1 with linear interpolation loops cleanly. Every LED state and button
press has to be back where it started by frame N.

`camera_path()` is for camera moves with some life in them: a list of holds, each a slow drift
from one pose to another, joined by quick moves. A move eases sharply (quintic) and starts and
ends at the neighbouring holds' drift speeds, so the camera never stops dead or jolts. The last
hold moves back into the first. A faint handheld float (sines with whole cycles per loop) goes
on top. The path is baked to one key per frame. A pose also carries `fstop` and `lens`, so a
move can rack focus or zoom while it travels.

## Units

Scene units are metres. The GLBs are in mm and their root empty is scaled by 0.001. Use `MM`
from studio.py for small distances (`2.5 * MM`).
