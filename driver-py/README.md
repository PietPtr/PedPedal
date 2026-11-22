# footswitch (Python)

Configure the PedPedal USB MIDI footswitch from Python: each pedal's MIDI message,
momentary/latch mode and LED colour. A straight port of the Rust `footswitch` crate in
`driver/`; see [docs/firmware.md](../docs/firmware.md) for the protocol.

```sh
uv add ./driver-py        # or: pip install ./driver-py
```

```python
from footswitch import Color, ControlChange, Footswitch, Mode, Note

with Footswitch.open() as fs:                 # first port with "Footswitch" in its name
    print(fs.info())                          # firmware version, connected pedals
    fs.set_mode(0, Mode.LATCH)                # pedal index from 0
    fs.set_color(0, Color.GREEN)
    fs.set_message(0, Note(channel=9, note=36, velocity=100))   # channel 0-15
    fs.set_message(1, ControlChange(channel=0, controller=64, on_value=127, off_value=0))
    fs.save()                                 # keep it after power-off
```

Also: `pedal`, `pedals`, `set_pedal`, `update_pedal`, `set_all_colors`, `settings`,
`set_settings`, `states`, `reset_defaults`, `enter_bootloader`, `list_ports`,
`all_port_names`. Errors are subclasses of `FootswitchError`.

Uses [python-rtmidi](https://pypi.org/project/python-rtmidi/). Tests: `uv run --group dev pytest`.
