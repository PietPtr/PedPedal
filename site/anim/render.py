"""Render a shot with Blender and encode it into a looping web video.

    uv run site/anim/render.py lookdev --stills 6          # 6 draft stills + contact sheet
    uv run site/anim/render.py lookdev                     # whole loop at 640x360, 15 fps
    uv run site/anim/render.py lookdev -q preview          # whole loop, 960x540, mp4 only
    uv run site/anim/render.py lookdev -q final            # 2560x1440: mp4 + webm + poster
    uv run site/anim/render.py lookdev --frames 1 60 120   # just these frames
    uv run site/anim/render.py lookdev -q preview -j 2     # two Blenders, each doing every 2nd frame
    uv run site/anim/render.py lookdev -q final --no-render  # only save the .blend (for a render farm)
    uv run site/anim/render.py lookdev -q final --encode-only  # encode frames rendered elsewhere

Every shot renders once, at the widest aspect (--aspect, default 21x9). The camera keeps its
vertical field of view, so the videos for narrower screens (--exports, default 21x9 and 16x9)
are centre crops of that one render, each with its own vignette (added by ffmpeg).

Loop frames go to site/anim/build/SHOT/QUALITY/frames/ (with SHOT.blend in QUALITY/, to open
the scene in Blender);
stills (--stills, --frames) and their sheet.png to site/anim/build/SHOT/QUALITY/stills/.
Videos go to site/media/ (final) or site/anim/build/SHOT/QUALITY/ (draft, preview), as
SHOT.{mp4,webm,jpg} for 16:9 and SHOT-21x9.* etc. for the others.
Blender is found via $BLENDER, then PATH, then ~/bin/blender.
"""
import argparse
import os
import shutil
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent
BUILD = HERE / 'build'
MEDIA = SITE / 'media'


def blender():
    for c in (os.environ.get('BLENDER'), shutil.which('blender'), str(Path.home() / 'bin' / 'blender')):
        if c and Path(c).exists():
            return c
    sys.exit('Blender not found: set $BLENDER')


def run_blender(shot, quality, out, frames, jobs=1, extra=()):
    """Render with `jobs` Blender processes side by side, each taking every jobs-th frame.
    EEVEE renders on the GPU, so this only helps by overlapping one process's CPU work (scene
    update, compositing, PNG writing) with another's GPU work."""
    t0, n, fps = time.time(), 0, None
    lines = queue.Queue()
    procs, logs = [], []
    for i in range(jobs):
        cmd = [blender(), '-b', '--factory-startup', '--python-exit-code', '1', '-P', str(HERE / 'main.py'), '--',
               shot, quality, str(out), '--part', f'{i}/{jobs}', *extra, *map(str, frames)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(p)
        logs.append([])
        threading.Thread(target=lambda i=i, p=p: ([lines.put((i, l)) for l in p.stdout],
                                                  lines.put((i, None))), daemon=True).start()
    running = jobs
    while running:
        i, line = lines.get()
        if line is None:
            running -= 1
            continue
        logs[i].append(line)
        if m := re.match(r'SHOT .*, ([\d.]+) fps', line):
            fps = float(m.group(1))
        if line.startswith('FRAME') or (line.startswith(('SHOT', 'BLEND')) and i == 0):
            n += line.startswith('FRAME')
            tag = f' (job {i})' if jobs > 1 and line.startswith('FRAME') else ''
            print(f'  [{time.time() - t0:6.1f}s] {line.strip()}{tag}', flush=True)
    failed = [(i, p.returncode) for i, p in enumerate(procs) if p.wait()]
    if failed:
        i, rc = failed[0]
        sys.stdout.write(''.join(logs[i][-40:]))
        sys.exit(f'blender job {i} failed ({rc})')
    return n, time.time() - t0, fps


def contact_sheet(pngs, dst, cols=3, guides=('16x9',)):
    """The frames side by side, with lines where the narrower exports crop them."""
    from PIL import Image, ImageDraw
    ims = [Image.open(p) for p in pngs]
    w, h = ims[0].size
    for im in ims:
        d = ImageDraw.Draw(im)
        for g in guides:
            cw = crop_width(h, g)
            if cw < w:
                x0 = (w - cw) // 2
                d.line([(x0, 0), (x0, h)], fill=(255, 200, 0), width=1)
                d.line([(x0 + cw, 0), (x0 + cw, h)], fill=(255, 200, 0), width=1)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * w, rows * h), (40, 40, 40))
    for i, (im, p) in enumerate(zip(ims, pngs)):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im, (x, y))
        ImageDraw.Draw(sheet).text((x + 6, y + 4), p.stem, fill=(255, 255, 0))
    sheet.save(dst)


def aspect_ratio(a):
    w, h = a.split('x')
    return float(w) / float(h)


def crop_width(h, a):
    return 2 * round(h * aspect_ratio(a) / 2)


def export_filter(frames_dir, a):
    """ffmpeg filter: centre crop to aspect `a`, then a vignette that follows the frame."""
    from PIL import Image
    w, h = Image.open(next(frames_dir.glob('[0-9][0-9][0-9][0-9].png'))).size
    cw = min(crop_width(h, a), w)
    return f'crop={cw}:{h},vignette=angle=0.3'          # subtle; its aspect option cuts in hard


def encode(frames_dir, fps, stem, webm=True, vf=None):
    """H.264 mp4 (plays everywhere) and VP9 webm (smaller), both without audio, plus a poster.
    Takes every PNG in frames_dir in name order, so gaps (draft's every-2nd frame) are fine.
    `vf` is an ffmpeg filter (crop + vignette) applied to all three."""
    src = ['-framerate', f'{fps:g}', '-pattern_type', 'glob', '-i', str(frames_dir / '[0-9][0-9][0-9][0-9]*.png')]  # needs a *: ffmpeg takes a glob without one literally
    if vf:
        src += ['-vf', vf]
    ff = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    mp4 = stem.with_suffix('.mp4')
    subprocess.run(ff + src + ['-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-pix_fmt', 'yuv420p',
                               '-movflags', '+faststart', '-an', str(mp4)], check=True)
    out = [mp4]
    if webm:
        w = stem.with_suffix('.webm')
        subprocess.run(ff + src + ['-c:v', 'libvpx-vp9', '-crf', '33', '-b:v', '0', '-row-mt', '1',
                                   '-deadline', 'good', '-cpu-used', '2', '-pix_fmt', 'yuv420p', '-an',
                                   str(w)], check=True)
        jpg = stem.with_suffix('.jpg')
        subprocess.run(ff + ['-i', str(frames_dir / '0001.png')] + (['-vf', vf] if vf else []) +
                       ['-q:v', '3', str(jpg)], check=True)
        out += [w, jpg]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('shot')
    ap.add_argument('-q', '--quality', default='draft', choices=['draft', 'preview', 'final'])
    ap.add_argument('--stills', type=int, help='render N evenly spaced frames and a contact sheet')
    ap.add_argument('--frames', type=int, nargs='+', help='render only these frames')
    ap.add_argument('--fps', type=float, help='video frame rate (default: from the shot and preset)')
    ap.add_argument('-j', '--jobs', type=int, default=1, help='Blender processes to run side by side')
    ap.add_argument('--no-render', action='store_true',
                    help='only build the shot and save a self-contained SHOT.blend (packed, frame '
                         'range and step set, output //frames/####.png), e.g. to upload to a render farm')
    ap.add_argument('--encode-only', action='store_true',
                    help='skip Blender and encode the frames already in build/SHOT/QUALITY/frames/ '
                         '(where both this script and a render farm write them)')
    ap.add_argument('--from', dest='src', type=Path, nargs='+', metavar='ZIP_OR_DIR',
                    help='with --encode-only: first copy the frames from these zips or folders (e.g. '
                         "a render farm's downloads; any *NNNN.png name) into build/SHOT/QUALITY/frames/")
    ap.add_argument('--length', type=int, help='loop length in frames, for --stills (default: ask the shot)')
    ap.add_argument('--aspect', default='21x9', help='aspect to render at: the widest export')
    ap.add_argument('--exports', default='21x9,16x9',
                    help='aspects to export, as centre crops of the render (16x9 is SHOT.*, '
                         'the others SHOT-WxH.*)')
    args = ap.parse_args()
    shots = sorted(p.stem for p in (HERE / 'shots').glob('*.py') if p.stem != '__init__')
    if args.shot not in shots:
        sys.exit(f'no shot {args.shot!r}: pick one of {", ".join(shots)}')
    exports = args.exports.split(',')
    if any(aspect_ratio(a) > aspect_ratio(args.aspect) for a in exports):
        sys.exit(f'every export must be at most as wide as the render ({args.aspect})')

    os.environ['ANIM_ASPECT'] = args.aspect          # read by studio.py inside Blender
    name = args.shot
    out = BUILD / name / args.quality
    frames = args.frames or []
    if args.stills:
        n = args.length or shot_length(args.shot)
        frames = [1 + round(i * n / args.stills) for i in range(args.stills)]
    if frames and not args.encode_only:
        out = out / 'stills'            # keep stills and their sheet apart from the loop's frames
    if args.no_render:
        print(f'{name} ({args.quality}, {args.aspect}): saving the .blend only')
        run_blender(args.shot, args.quality, out, [], extra=['--no-render'])
        print(f'wrote {out / f"{name}.blend"}: render it, put the frames in {out}/frames/, '
              f'then run this again with --encode-only instead of --no-render')
        return
    src = out if frames else out / 'frames'     # where the frames to encode are
    if args.encode_only:
        if args.src:
            n = import_frames(args.src, src)
            print(f'copied {n} frames from {", ".join(map(str, args.src))} to {src}')
        if not list(src.glob('[0-9][0-9][0-9][0-9].png')):
            sys.exit(f'no ####.png frames in {src}')
        fps = None
    elif src.exists() and not frames:
        for p in src.glob('*.png'):
            p.unlink()
    if not args.encode_only:
        print(f'{name} ({args.quality}) -> {out}')
        n, secs, fps = run_blender(args.shot, args.quality, out, frames, max(args.jobs, 1))
        print(f'{n} frames in {secs:.0f} s ({secs / max(n, 1):.1f} s/frame, incl. scene setup)')

    if frames and not args.encode_only:
        sheet = out / 'sheet.png'
        contact_sheet([out / f'{f:04d}.png' for f in frames], sheet,
                      guides=[a for a in exports if a != args.aspect])
        print(f'contact sheet: {sheet}')
    else:
        final = args.quality == 'final'
        for a in exports:
            stem = (MEDIA if final else BUILD / name / args.quality) / (name if a == '16x9' else f'{name}-{a}')
            stem.parent.mkdir(parents=True, exist_ok=True)
            for f in encode(src, args.fps or fps or 30, stem, webm=final, vf=export_filter(src, a)):
                print(f'wrote {f} ({f.stat().st_size / 1e6:.1f} MB)')


def import_frames(srcs, dst):
    """Copy the PNGs from zips or folders into dst as ####.png, numbered by the digits at the end
    of their names (render farms write e.g. pedals_00001.png). Replaces dst's old frames. Later
    sources win where frame numbers overlap. Warns about missing frames."""
    import zipfile
    frames = {}
    for src in srcs:
        if src.is_dir():
            items = [(p.name, p.read_bytes) for p in src.rglob('*.png')]
        else:
            z = zipfile.ZipFile(src)
            items = [(n, lambda z=z, n=n: z.read(n)) for n in z.namelist() if n.endswith('.png')]
        for n, read in items:
            if m := re.search(r'(\d+)\.png$', Path(n).name):
                frames[int(m.group(1))] = read
    if not frames:
        sys.exit(f'no numbered PNGs in {", ".join(map(str, srcs))}')
    missing = sorted(set(range(1, max(frames) + 1)) - set(frames))
    if missing:
        print(f'warning: {len(missing)} frames missing, e.g. {missing[:10]}')
    dst.mkdir(parents=True, exist_ok=True)
    for p in dst.glob('*.png'):
        p.unlink()
    for f, read in frames.items():
        (dst / f'{f:04d}.png').write_bytes(read())
    return len(frames)


def shot_length(shot):
    """Frame count of a shot, from its set_frames() call (no Blender needed)."""
    import re
    text = (HERE / 'shots' / f'{shot}.py').read_text()
    m = re.search(r'set_frames\((\d+)', text)
    return int(m.group(1)) if m else 120


if __name__ == '__main__':
    main()
