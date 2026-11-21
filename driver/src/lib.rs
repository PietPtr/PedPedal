//! Host driver for the USB MIDI footswitch.
//!
//! The device shows up as a USB MIDI port called "Footswitch". It sends its pedal messages on
//! that port, and the same port takes configuration as SysEx (see
//! [`footswitch_core::protocol`]). No OS driver is needed.
//!
//! ```no_run
//! use footswitch::{Color, Footswitch, Message, Mode};
//!
//! let mut fs = Footswitch::open()?;
//! println!("{} pedals connected", fs.info()?.connected_pedals);
//!
//! // Pedal 0 (the module with the Pico): latching, green, sends CC 64 on channel 1.
//! fs.set_mode(0, Mode::Latch)?;
//! fs.set_color(0, Color::Green)?;
//! fs.set_message(0, Message::ControlChange { channel: 0, controller: 64, on_value: 127, off_value: 0 })?;
//! fs.save()?; // keep it after power-off
//! # Ok::<(), footswitch::Error>(())
//! ```
//!
//! Pedal indices start at 0 (the module with the Pico) and MIDI channels are 0–15
//! (channel 1 is 0). Changes apply at once; call [`Footswitch::save`] to keep them in flash.
//!
//! On Windows a MIDI port can only be open in one program at a time, so close the DAW (or
//! disable the port in it) while configuring.

use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::{Duration, Instant};

use footswitch_core::protocol::{self, Command, Request, Response};
use midir::{Ignore, MidiInput, MidiInputConnection, MidiOutput, MidiOutputConnection};

pub use footswitch_core::protocol::{DeviceInfo, PedalStates, Status};
pub use footswitch_core::{Color, MAX_PEDALS, Message, Mode, PedalConfig, Settings};

/// Substring of the USB product name that [`Footswitch::open`] looks for in port names.
pub const PORT_NAME: &str = "Footswitch";

/// How long to wait for a reply. Saving to flash takes about 50 ms.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_millis(1000);

const CLIENT_NAME: &str = "footswitch-driver";

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("no MIDI port matching {0:?} found (is the footswitch plugged in?)")]
    NotFound(String),
    #[error("MIDI system error: {0}")]
    Midi(String),
    #[error("sending to the device failed: {0}")]
    Send(#[from] midir::SendError),
    #[error("no reply from the device to {0:?}")]
    Timeout(Command),
    #[error("the device rejected {command:?}: {status:?}")]
    Rejected { command: Command, status: Status },
    #[error("unexpected reply to {0:?}")]
    UnexpectedReply(Command),
    #[error("pedal index {0} out of range (max {max})", max = MAX_PEDALS - 1)]
    BadIndex(usize),
    #[error("invalid pedal config: {0:?}")]
    InvalidConfig(PedalConfig),
}

pub type Result<T, E = Error> = std::result::Result<T, E>;

/// Lists the MIDI input port names that contain [`PORT_NAME`].
pub fn list_ports() -> Result<Vec<String>> {
    let names = all_port_names()?;
    Ok(names.into_iter().filter(|n| n.contains(PORT_NAME)).collect())
}

/// Lists every MIDI input port name, footswitch or not. Useful when the device's port has an
/// unexpected name.
pub fn all_port_names() -> Result<Vec<String>> {
    let input = MidiInput::new(CLIENT_NAME).map_err(|e| Error::Midi(e.to_string()))?;
    Ok(input.ports().iter().filter_map(|p| input.port_name(p).ok()).collect())
}

/// An open connection to a footswitch.
pub struct Footswitch {
    out: MidiOutputConnection,
    _in: MidiInputConnection<mpsc::Sender<Vec<u8>>>,
    rx: Receiver<Vec<u8>>,
    port_name: String,
    timeout: Duration,
}

impl Footswitch {
    /// Opens the first port whose name contains [`PORT_NAME`].
    pub fn open() -> Result<Self> {
        Self::open_matching(PORT_NAME)
    }

    /// Opens the first port whose name contains `pattern`. Use this to pick one of several
    /// footswitches, or a port with an unexpected name.
    pub fn open_matching(pattern: &str) -> Result<Self> {
        let mut input = MidiInput::new(CLIENT_NAME).map_err(|e| Error::Midi(e.to_string()))?;
        input.ignore(Ignore::None); // we need SysEx
        let output = MidiOutput::new(CLIENT_NAME).map_err(|e| Error::Midi(e.to_string()))?;

        let in_port = input
            .ports()
            .into_iter()
            .find(|p| input.port_name(p).is_ok_and(|n| n.contains(pattern)))
            .ok_or_else(|| Error::NotFound(pattern.into()))?;
        let out_port = output
            .ports()
            .into_iter()
            .find(|p| output.port_name(p).is_ok_and(|n| n.contains(pattern)))
            .ok_or_else(|| Error::NotFound(pattern.into()))?;
        let port_name = output.port_name(&out_port).unwrap_or_default();

        let (tx, rx) = mpsc::channel();
        let conn_in = input
            .connect(
                &in_port,
                "footswitch-in",
                |_stamp, msg, tx: &mut mpsc::Sender<Vec<u8>>| {
                    if msg.first() == Some(&0xF0) {
                        let _ = tx.send(msg.to_vec());
                    }
                },
                tx,
            )
            .map_err(|e| Error::Midi(e.to_string()))?;
        let conn_out =
            output.connect(&out_port, "footswitch-out").map_err(|e| Error::Midi(e.to_string()))?;

        Ok(Footswitch {
            out: conn_out,
            _in: conn_in,
            rx,
            port_name,
            timeout: DEFAULT_TIMEOUT,
        })
    }

    /// The name of the MIDI output port in use.
    pub fn port_name(&self) -> &str {
        &self.port_name
    }

    pub fn set_timeout(&mut self, timeout: Duration) {
        self.timeout = timeout;
    }

    /// Firmware version, and how many pedals are connected.
    pub fn info(&mut self) -> Result<DeviceInfo> {
        match self.request(Request::GetInfo)? {
            Response::Info(i) => Ok(i),
            _ => Err(Error::UnexpectedReply(Command::GetInfo)),
        }
    }

    /// The config of pedal `index`.
    pub fn pedal(&mut self, index: usize) -> Result<PedalConfig> {
        let index = check_index(index)?;
        match self.request(Request::GetPedal { index })? {
            Response::Pedal { index: i, config } if i == index => Ok(config),
            _ => Err(Error::UnexpectedReply(Command::GetPedal)),
        }
    }

    /// The configs of the connected pedals, in order.
    pub fn pedals(&mut self) -> Result<Vec<PedalConfig>> {
        let n = self.info()?.connected_pedals as usize;
        (0..n).map(|i| self.pedal(i)).collect()
    }

    /// Replaces pedal `index`'s config. If the pedal is on, the device first sends its old
    /// "off" message and turns it off.
    pub fn set_pedal(&mut self, index: usize, config: &PedalConfig) -> Result<()> {
        let index = check_index(index)?;
        if !config.is_valid() {
            return Err(Error::InvalidConfig(*config));
        }
        self.request(Request::SetPedal { index, config: *config }).map(drop)
    }

    /// Changes one pedal's mode, keeping its other settings.
    pub fn set_mode(&mut self, index: usize, mode: Mode) -> Result<()> {
        self.update_pedal(index, |p| p.mode = mode)
    }

    /// Changes one pedal's LED colour (shown while the pedal is on).
    pub fn set_color(&mut self, index: usize, color: Color) -> Result<()> {
        self.update_pedal(index, |p| p.color = color)
    }

    /// Changes the MIDI message one pedal sends.
    pub fn set_message(&mut self, index: usize, message: Message) -> Result<()> {
        self.update_pedal(index, |p| p.message = message)
    }

    /// Reads pedal `index`, applies `f` and writes it back.
    pub fn update_pedal(&mut self, index: usize, f: impl FnOnce(&mut PedalConfig)) -> Result<()> {
        let mut cfg = self.pedal(index)?;
        f(&mut cfg);
        self.set_pedal(index, &cfg)
    }

    /// Sets the LED colour of every pedal.
    pub fn set_all_colors(&mut self, color: Color) -> Result<()> {
        for i in 0..MAX_PEDALS {
            self.set_color(i, color)?;
        }
        Ok(())
    }

    pub fn settings(&mut self) -> Result<Settings> {
        match self.request(Request::GetSettings)? {
            Response::Settings(s) => Ok(s),
            _ => Err(Error::UnexpectedReply(Command::GetSettings)),
        }
    }

    pub fn set_settings(&mut self, settings: Settings) -> Result<()> {
        self.request(Request::SetSettings(settings)).map(drop)
    }

    /// Which pedals are on and which switches are held down right now.
    pub fn states(&mut self) -> Result<PedalStates> {
        match self.request(Request::GetState)? {
            Response::State(s) => Ok(s),
            _ => Err(Error::UnexpectedReply(Command::GetState)),
        }
    }

    /// Writes the current config to flash, so it survives a power cycle.
    pub fn save(&mut self) -> Result<()> {
        self.request(Request::Save).map(drop)
    }

    /// Restores the factory defaults (every pedal momentary, red, CC 102 + index on channel
    /// 1). Only in RAM: call [`save`](Self::save) to make it permanent.
    pub fn reset_defaults(&mut self) -> Result<()> {
        self.request(Request::ResetDefaults).map(drop)
    }

    /// Reboots the Pico into its USB bootloader (the RPI-RP2 drive) for a firmware update,
    /// without pressing BOOTSEL. The connection is dead afterwards.
    pub fn enter_bootloader(mut self) -> Result<()> {
        match self.request(Request::EnterBootloader) {
            // The reply can be lost when USB goes down; that is fine here.
            Ok(_) | Err(Error::Timeout(_)) => Ok(()),
            Err(e) => Err(e),
        }
    }

    /// Sends one request and waits for its reply.
    pub fn request(&mut self, req: Request) -> Result<Response> {
        // Drop stale replies (e.g. from an earlier request that timed out).
        while self.rx.try_recv().is_ok() {}
        self.out.send(req.encode().as_bytes())?;

        let command = req.command();
        let deadline = Instant::now() + self.timeout;
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            let msg = match self.rx.recv_timeout(left) {
                Ok(m) => m,
                Err(RecvTimeoutError::Timeout | RecvTimeoutError::Disconnected) => {
                    return Err(Error::Timeout(command));
                }
            };
            let Some(reply) = protocol::decode_response(&msg) else { continue };
            if reply.command != command as u8 {
                continue;
            }
            return reply.result.map_err(|status| Error::Rejected { command, status });
        }
    }
}

fn check_index(index: usize) -> Result<u8> {
    if index < MAX_PEDALS { Ok(index as u8) } else { Err(Error::BadIndex(index)) }
}
