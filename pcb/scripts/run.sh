#!/bin/bash
# Rebuild the board from the schematic, autoroute it with Freerouting, fill zones and run DRC.
# Usage: scripts/run.sh WORKDIR    (WORKDIR holds intermediate files; use a scratch directory)
# The result is WORKDIR/footswitch_drc.kicad_pcb. Copy it to pcb/footswitch.kicad_pcb when happy.
# Note: this regenerates the board from scratch, so manual edits made in KiCad are lost.
set -e
SCRIPTS=$(cd "$(dirname "$0")" && pwd)
PCB=$(dirname "$SCRIPTS")
WORK=${1:?usage: run.sh WORKDIR}
mkdir -p "$WORK" && cd "$WORK"

kicad-cli sch export netlist "$PCB/footswitch.kicad_sch" -o net.xml --format kicadxml >/dev/null
python3 "$SCRIPTS/pcbgen.py" net.xml footswitch.kicad_pcb        # also writes footswitch.dsn
rm -f footswitch.ses
# Use the system Java: the runtime bundled with Freerouting 2.1.0 lacks java.management and
# throws NoClassDefFoundError. No display, so Freerouting can't pop up dialogs.
env -u DISPLAY -u WAYLAND_DISPLAY timeout 600 java -Djava.awt.headless=true \
  -jar ~/Downloads/freerouting-2.1.0-linux-x64/lib/app/freerouting-executable.jar \
  -de footswitch.dsn -do footswitch.ses --router.max_passes=40 --router.optimizer.max_passes=20 \
  --gui.enabled=false > fr.log 2>&1 || true
grep 'pass #' fr.log | tail -1 | grep -o 'score of [^,]*([^)]*)' || true
python3 "$SCRIPTS/sesimport.py" footswitch.ses routes.json
python3 "$SCRIPTS/pcbgen.py" net.xml footswitch_drc.kicad_pcb routes.json
rm -f footswitch_drc.dsn
cp "$PCB/fp-lib-table" .
cp "$PCB/footswitch.kicad_dru" footswitch_drc.kicad_dru
cp "$PCB/footswitch.kicad_pro" footswitch_drc.kicad_pro
kicad-cli pcb drc footswitch_drc.kicad_pcb -o drc.rpt --refill-zones --save-board --schematic-parity >/dev/null 2>&1 || true
grep -E '^\[' drc.rpt | sort | uniq -c | sort -rn || true
grep 'Found' drc.rpt
