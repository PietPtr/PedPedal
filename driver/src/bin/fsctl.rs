//! fsctl: configure the footswitch from the command line.
//!
//! Pedals are numbered from 1 (the module with the Pico) and MIDI channels 1–16, as on most
//! MIDI gear. The library underneath counts both from 0.

use std::process::ExitCode;
use std::time::Duration;

use clap::{Parser, Subcommand, ValueEnum};
use footswitch::{Color, Footswitch, MAX_PEDALS, Message, Mode, PedalConfig, Settings};

#[derive(Parser)]
#[command(version, about = "Configure the USB MIDI footswitch")]
struct Cli {
    /// Use the first MIDI port whose name contains this text.
    #[arg(long, global = true, default_value = footswitch::PORT_NAME)]
    port: String,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// List MIDI ports (all of them, footswitch or not).
    Ports,
    /// Show firmware version, connected pedals and every pedal's config.
    Show,
    /// Change one pedal (or all of them). Settings not given are kept.
    ///
    /// Examples:
    ///   fsctl set 1 --mode latch --color green
    ///   fsctl set 2 --cc 64 --channel 1 --on 127 --off 0
    ///   fsctl set 3 --note 36 --velocity 100 --channel 10
    ///   fsctl set 4 --pc 5
    ///   fsctl set all --color blue
    #[command(verbatim_doc_comment)]
    Set(SetArgs),
    /// Print which pedals are on / held down.
    State {
        /// Keep printing changes until Ctrl-C.
        #[arg(long)]
        watch: bool,
    },
    /// Read the switches inverted (for switches with NO and NC swapped).
    Invert {
        #[arg(value_parser = ["on", "off"])]
        value: String,
    },
    /// Write the current config to flash, so it survives power-off.
    Save,
    /// Restore factory defaults (momentary, red, CC 102+ on channel 1). Run `save` to keep them.
    Reset,
    /// Reboot into the USB bootloader for a firmware update (the RPI-RP2 drive appears).
    Bootloader,
}

#[derive(clap::Args)]
struct SetArgs {
    /// Pedal number from 1, or "all".
    pedal: String,
    #[arg(long)]
    mode: Option<ModeArg>,
    #[arg(long)]
    color: Option<ColorArg>,

    /// Send this note (0–127): Note On when on, Note Off when off.
    #[arg(long, group = "kind", value_parser = clap::value_parser!(u8).range(0..128))]
    note: Option<u8>,
    /// Send this controller (0–127): `--on` value when on, `--off` value when off.
    #[arg(long, group = "kind", value_parser = clap::value_parser!(u8).range(0..128))]
    cc: Option<u8>,
    /// Send this program change (0–127) when the pedal turns on.
    #[arg(long, group = "kind", value_parser = clap::value_parser!(u8).range(0..128))]
    pc: Option<u8>,
    /// Send no MIDI at all (the LED still works).
    #[arg(long, group = "kind")]
    no_midi: bool,

    /// MIDI channel, 1–16.
    #[arg(long, value_parser = clap::value_parser!(u8).range(1..=16))]
    channel: Option<u8>,
    /// Note velocity, 1–127 (default 127).
    #[arg(long, value_parser = clap::value_parser!(u8).range(1..128))]
    velocity: Option<u8>,
    /// CC value sent when the pedal turns on (default 127).
    #[arg(long, value_parser = clap::value_parser!(u8).range(0..128))]
    on: Option<u8>,
    /// CC value sent when the pedal turns off (default 0).
    #[arg(long, value_parser = clap::value_parser!(u8).range(0..128))]
    off: Option<u8>,

    /// Also save to flash.
    #[arg(long)]
    save: bool,
}

#[derive(Clone, Copy, ValueEnum)]
enum ModeArg {
    Momentary,
    Latch,
}

#[derive(Clone, Copy, ValueEnum)]
enum ColorArg {
    Off,
    Red,
    Green,
    Yellow,
    Blue,
    Magenta,
    Cyan,
    White,
}

impl From<ColorArg> for Color {
    fn from(c: ColorArg) -> Color {
        match c {
            ColorArg::Off => Color::Off,
            ColorArg::Red => Color::Red,
            ColorArg::Green => Color::Green,
            ColorArg::Yellow => Color::Yellow,
            ColorArg::Blue => Color::Blue,
            ColorArg::Magenta => Color::Magenta,
            ColorArg::Cyan => Color::Cyan,
            ColorArg::White => Color::White,
        }
    }
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match run(cli) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}

type Res = Result<(), Box<dyn std::error::Error>>;

fn run(cli: Cli) -> Res {
    if let Cmd::Ports = cli.cmd {
        for name in footswitch::all_port_names()? {
            let mark = if name.contains(&cli.port) { "*" } else { " " };
            println!("{mark} {name}");
        }
        return Ok(());
    }

    let mut fs = Footswitch::open_matching(&cli.port)?;
    match cli.cmd {
        Cmd::Ports => unreachable!(),
        Cmd::Show => show(&mut fs)?,
        Cmd::Set(args) => set(&mut fs, &args)?,
        Cmd::State { watch } => state(&mut fs, watch)?,
        Cmd::Invert { value } => {
            fs.set_settings(Settings { invert_switches: value == "on" })?;
            println!("switch inversion {value} (run `fsctl save` to keep it)");
        }
        Cmd::Save => {
            fs.save()?;
            println!("saved to flash");
        }
        Cmd::Reset => {
            fs.reset_defaults()?;
            println!("defaults restored (run `fsctl save` to keep them)");
        }
        Cmd::Bootloader => {
            fs.enter_bootloader()?;
            println!("rebooting into the bootloader; copy the .uf2 to the RPI-RP2 drive");
        }
    }
    Ok(())
}

fn show(fs: &mut Footswitch) -> Res {
    let info = fs.info()?;
    let [a, b, c] = info.firmware_version;
    println!("port:      {}", fs.port_name());
    println!("firmware:  {a}.{b}.{c} (protocol {})", info.protocol_version);
    println!("pedals:    {} connected (max {})", info.connected_pedals, info.max_pedals);
    println!("inverted:  {}", if fs.settings()?.invert_switches { "yes" } else { "no" });
    let states = fs.states()?;
    // Show at least one pedal, so the defaults are visible even with no modules detected.
    let n = (info.connected_pedals as usize).max(1);
    println!();
    println!("pedal  mode       color    on    midi");
    for i in 0..n {
        let p = fs.pedal(i)?;
        let on = if states.active & (1 << i) != 0 { "on" } else { "-" };
        println!(
            "{:<6} {:<10} {:<8} {:<5} {}",
            i + 1,
            mode_name(p.mode),
            p.color.name(),
            on,
            describe(&p.message)
        );
    }
    Ok(())
}

fn set(fs: &mut Footswitch, a: &SetArgs) -> Res {
    let pedals: Vec<usize> = if a.pedal.eq_ignore_ascii_case("all") {
        (0..MAX_PEDALS).collect()
    } else {
        let n: usize = a.pedal.parse().map_err(|_| format!("bad pedal number {:?}", a.pedal))?;
        if !(1..=MAX_PEDALS).contains(&n) {
            return Err(format!("pedal must be 1–{MAX_PEDALS} or \"all\"").into());
        }
        vec![n - 1]
    };
    for &i in &pedals {
        let mut p = fs.pedal(i)?;
        apply(&mut p, a);
        fs.set_pedal(i, &p)?;
        if pedals.len() == 1 {
            println!("pedal {}: {} {} {}", i + 1, mode_name(p.mode), p.color.name(), describe(&p.message));
        }
    }
    if pedals.len() > 1 {
        println!("updated all {} pedals", pedals.len());
    }
    if a.save {
        fs.save()?;
        println!("saved to flash");
    }
    Ok(())
}

/// Applies the command-line changes to a pedal config.
fn apply(p: &mut PedalConfig, a: &SetArgs) {
    if let Some(m) = a.mode {
        p.mode = match m {
            ModeArg::Momentary => Mode::Momentary,
            ModeArg::Latch => Mode::Latch,
        };
    }
    if let Some(c) = a.color {
        p.color = c.into();
    }

    // Values from the existing message, used where an option isn't given.
    let (old_ch, old_vel, old_on, old_off) = match p.message {
        Message::None => (0, 127, 127, 0),
        Message::Note { channel, velocity, .. } => (channel, velocity, 127, 0),
        Message::ControlChange { channel, on_value, off_value, .. } => {
            (channel, 127, on_value, off_value)
        }
        Message::ProgramChange { channel, .. } => (channel, 127, 127, 0),
    };
    let channel = a.channel.map(|c| c - 1).unwrap_or(old_ch);
    let velocity = a.velocity.unwrap_or(old_vel);
    let on_value = a.on.unwrap_or(old_on);
    let off_value = a.off.unwrap_or(old_off);

    p.message = if let Some(note) = a.note {
        Message::Note { channel, note, velocity }
    } else if let Some(controller) = a.cc {
        Message::ControlChange { channel, controller, on_value, off_value }
    } else if let Some(program) = a.pc {
        Message::ProgramChange { channel, program }
    } else if a.no_midi {
        Message::None
    } else {
        // Same kind of message; only channel/velocity/values change.
        match p.message {
            Message::None => Message::None,
            Message::Note { note, .. } => Message::Note { channel, note, velocity },
            Message::ControlChange { controller, .. } => {
                Message::ControlChange { channel, controller, on_value, off_value }
            }
            Message::ProgramChange { program, .. } => Message::ProgramChange { channel, program },
        }
    };
}

fn state(fs: &mut Footswitch, watch: bool) -> Res {
    let mut last = None;
    loop {
        let s = fs.states()?;
        if last != Some(s) {
            let mut line = format!("{} connected:", s.connected);
            for i in 0..s.connected as usize {
                let c = match (s.active >> i & 1 != 0, s.pressed >> i & 1 != 0) {
                    (true, true) => "ON*",
                    (true, false) => "ON ",
                    (false, true) => "-* ",
                    (false, false) => "-  ",
                };
                line += &format!("  {}:{c}", i + 1);
            }
            println!("{line}");
            last = Some(s);
        }
        if !watch {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn mode_name(m: Mode) -> &'static str {
    match m {
        Mode::Momentary => "momentary",
        Mode::Latch => "latch",
    }
}

fn describe(m: &Message) -> String {
    match *m {
        Message::None => "none".into(),
        Message::Note { channel, note, velocity } => {
            format!("note {note} vel {velocity} ch {}", channel + 1)
        }
        Message::ControlChange { channel, controller, on_value, off_value } => {
            format!("cc {controller} on {on_value} off {off_value} ch {}", channel + 1)
        }
        Message::ProgramChange { channel, program } => {
            format!("pc {program} ch {}", channel + 1)
        }
    }
}
