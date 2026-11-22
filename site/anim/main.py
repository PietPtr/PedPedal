"""Blender entry point: builds one shot and renders it. Started by render.py:

    blender -b --factory-startup -P site/anim/main.py -- SHOT QUALITY OUTDIR [--part I/N] [--no-render] [FRAME ...]

Without frames it renders the whole loop (frames 1..N, or every 2nd one in draft: the preset's
step) to OUTDIR/frames/####.png, named by frame number. With frames, only those, to
OUTDIR/####.png. It also saves OUTDIR/SHOT.blend, to open the scene in Blender.

With --part I/N (I counts from 0) it renders every Nth of those frames, starting at the Ith, so
N Blenders can share one render. Only part 0 saves the .blend.

The saved .blend is self-contained, for a render farm: external files are packed, the frame
step is the preset's, and the output path is //frames/####.png (next to the .blend). With
--no-render it only saves the .blend.
"""
import importlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import bpy  # noqa: E402, F401
except ImportError:
    sys.exit('main.py runs inside Blender. Start it through render.py, e.g.:\n'
             '    uv run site/anim/render.py SHOT -q final --no-render')

import studio  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    no_render = '--no-render' in argv
    argv = [a for a in argv if a != '--no-render']
    shot, quality, outdir, *frames = argv
    part, nparts = 0, 1
    if frames[:1] == ['--part']:
        part, nparts = map(int, frames[1].split('/'))
        frames = frames[2:]
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    mod = importlib.import_module(f'shots.{shot}')
    s = studio.Studio(quality)
    mod.build(s)
    s.finish()
    sc = s.scene
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_depth = '8'
    step = s.q['step']
    sc.frame_step = step
    if part == 0:
        sc.render.filepath = '//frames/####'
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=str(outdir / f'{shot}.blend'))
        print(f'BLEND {outdir / f"{shot}.blend"}', flush=True)
    if no_render:
        return
    fps = sc.render.fps / step
    print(f'SHOT {shot}: {s.frames} frames, {quality}, {fps:g} fps', flush=True)
    todo = [int(f) for f in frames] if frames else range(1, s.frames + 1, step)
    todo = list(todo)[part::nparts]
    dst = outdir if frames else outdir / 'frames'   # a whole loop goes in frames/, like the render farm's
    for f in todo:
        sc.frame_set(f)
        sc.render.filepath = str(dst / f'{f:04d}.png')
        bpy.ops.render.render(write_still=True)
        print(f'FRAME {f}', flush=True)


main()
