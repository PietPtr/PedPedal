//! The pedal state machine: chain decoding, debouncing, momentary/latch, LEDs and MIDI output.
//!
//! The firmware calls [`Engine::scan`] once per chain scan (every [`SCAN_INTERVAL_US`]) with the
//! switch bytes it read, and drives the LEDs from [`Engine::led_bits`].

use crate::config::{Config, Mode, PedalConfig};
use crate::protocol::PedalStates;
use crate::{MAX_PEDALS, ShortMessage};

/// How often the firmware scans the chain.
pub const SCAN_INTERVAL_US: u32 = 1000;

/// A switch change must be seen on this many scans in a row to count. Filters single-scan
/// glitches on the ribbon cable.
const CONFIRM_SCANS: u8 = 2;

/// After a change is accepted, the next change is held back for this many scans. This rides out
/// contact bounce without delaying the first edge.
const LOCKOUT_SCANS: u8 = 20;

/// Bit 7 of each module's switch byte (74HC165 input H) is tied high.
const MARKER_BIT: u8 = 0x80;
/// Bit 6 (input G) is the footswitch, active low.
const SWITCH_BIT: u8 = 0x40;

/// Decodes the switch bytes read from the chain (module 1 first).
///
/// Returns the number of connected modules (the first byte without the marker bit ends the
/// chain) and a mask of pressed switches, with `invert` applied.
pub fn decode_chain(bytes: &[u8], invert: bool) -> (usize, u16) {
    let mut pressed = 0u16;
    let mut connected = 0;
    for (i, &b) in bytes.iter().take(MAX_PEDALS).enumerate() {
        if b & MARKER_BIT == 0 {
            break;
        }
        connected = i + 1;
        let down = (b & SWITCH_BIT == 0) != invert;
        if down {
            pressed |= 1 << i;
        }
    }
    (connected, pressed)
}

#[derive(Clone, Copy, Default)]
struct Pedal {
    /// Debounced switch state.
    pressed: bool,
    /// Pedal is on: LED lit, "on" message sent.
    active: bool,
    /// Scans in a row where the raw input differed from `pressed`.
    pending: u8,
    lockout: u8,
}

pub struct Engine {
    pedals: [Pedal; MAX_PEDALS],
    connected: u8,
    /// Take the next scan's switch positions as they are, without generating presses.
    resync: bool,
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

impl Engine {
    pub const fn new() -> Self {
        Engine {
            pedals: [Pedal { pressed: false, active: false, pending: 0, lockout: 0 }; MAX_PEDALS],
            connected: 0,
            resync: true,
        }
    }

    /// Makes the next scan adopt the switch positions as they are, without treating any change
    /// as a press or release. The engine starts this way, so a switch that reads as pressed at
    /// power-on does nothing. Call it after changing `invert_switches`, which would otherwise
    /// look like every switch changing at once.
    ///
    /// A momentary pedal that is on but whose switch now reads as up is turned off.
    pub fn resync(&mut self) {
        self.resync = true;
    }

    /// Processes one scan. `chain` holds the switch bytes, module 1 first. Calls `send` for
    /// every MIDI message to send.
    pub fn scan(&mut self, config: &Config, chain: &[u8], mut send: impl FnMut(ShortMessage)) {
        let (connected, raw) = decode_chain(chain, config.settings.invert_switches);
        self.connected = connected as u8;
        if self.resync {
            self.resync = false;
            for i in 0..MAX_PEDALS {
                let down = raw & (1 << i) != 0;
                let p = &mut self.pedals[i];
                p.pressed = down;
                p.pending = 0;
                if config.pedals[i].mode == Mode::Momentary && !down {
                    self.set_active(i, &config.pedals[i], false, &mut send);
                }
            }
            return;
        }
        for i in 0..MAX_PEDALS {
            // A missing module reads as released, so a held pedal is let go if it's unplugged.
            let down = raw & (1 << i) != 0;
            let p = &mut self.pedals[i];
            p.lockout = p.lockout.saturating_sub(1);
            if down == p.pressed {
                p.pending = 0;
                continue;
            }
            p.pending = p.pending.saturating_add(1);
            if p.pending < CONFIRM_SCANS || p.lockout > 0 {
                continue;
            }
            p.pressed = down;
            p.pending = 0;
            p.lockout = LOCKOUT_SCANS;

            let cfg = &config.pedals[i];
            let target = match (cfg.mode, down) {
                (Mode::Momentary, d) => d,
                (Mode::Latch, true) => !p.active,
                (Mode::Latch, false) => continue,
            };
            self.set_active(i, cfg, target, &mut send);
        }
    }

    fn set_active(
        &mut self,
        i: usize,
        cfg: &PedalConfig,
        on: bool,
        send: &mut impl FnMut(ShortMessage),
    ) {
        let p = &mut self.pedals[i];
        if p.active == on {
            return;
        }
        p.active = on;
        let msg = if on { cfg.message.on_message() } else { cfg.message.off_message() };
        if let Some(m) = msg {
            send(m);
        }
    }

    /// Turns pedal `i` off, sending its off message under its current (`old`) config. Call this
    /// before changing a pedal's config, so no note or CC is left hanging.
    pub fn release(&mut self, i: usize, old: &PedalConfig, mut send: impl FnMut(ShortMessage)) {
        if i < MAX_PEDALS {
            self.set_active(i, old, false, &mut send);
        }
    }

    /// Turns every pedal off (see [`release`](Self::release)).
    pub fn release_all(&mut self, old: &Config, mut send: impl FnMut(ShortMessage)) {
        for i in 0..MAX_PEDALS {
            self.set_active(i, &old.pedals[i], false, &mut send);
        }
    }

    /// The 595 LED bits for pedal `i`: its colour while active, otherwise 0.
    pub fn led_bits(&self, config: &Config, i: usize) -> u8 {
        if self.pedals[i].active { config.pedals[i].color.bits() } else { 0 }
    }

    pub fn connected(&self) -> usize {
        self.connected as usize
    }

    pub fn states(&self) -> PedalStates {
        let mut s = PedalStates { connected: self.connected, ..Default::default() };
        for (i, p) in self.pedals.iter().enumerate() {
            s.active |= (p.active as u16) << i;
            s.pressed |= (p.pressed as u16) << i;
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Color, Message};
    use std::vec::Vec;

    const UP: u8 = MARKER_BIT | SWITCH_BIT | 0x3F;
    const DOWN: u8 = MARKER_BIT | 0x3F;

    /// A fresh engine that has done its first (resync) scan with every switch up.
    fn engine(cfg: &Config) -> Engine {
        let mut e = Engine::new();
        assert!(run(&mut e, cfg, &[UP; MAX_PEDALS], 1).is_empty());
        e
    }

    /// Runs `scans` scans with the given chain bytes, returning the messages sent.
    fn run(e: &mut Engine, cfg: &Config, chain: &[u8], scans: usize) -> Vec<Vec<u8>> {
        let mut out = Vec::new();
        for _ in 0..scans {
            e.scan(cfg, chain, |m| out.push(m.as_bytes().to_vec()));
        }
        out
    }

    #[test]
    fn chain_decoding() {
        assert_eq!(decode_chain(&[UP, DOWN, UP, 0, 0], false), (3, 0b010));
        assert_eq!(decode_chain(&[UP, DOWN, UP, 0, 0], true), (3, 0b101));
        assert_eq!(decode_chain(&[0; 16], false), (0, 0));
        // A missing module ends the chain even if later bytes look valid.
        assert_eq!(decode_chain(&[DOWN, 0, DOWN], false), (1, 1));
    }

    #[test]
    fn momentary() {
        let cfg = Config::default();
        let mut e = engine(&cfg);
        assert!(run(&mut e, &cfg, &[UP, UP], 5).is_empty());
        // Press: needs CONFIRM_SCANS scans.
        assert!(run(&mut e, &cfg, &[UP, DOWN], 1).is_empty());
        assert_eq!(run(&mut e, &cfg, &[UP, DOWN], 1), [[0xB0, 103, 127]]);
        assert_eq!(e.led_bits(&cfg, 1), Color::Red.bits());
        assert_eq!(e.led_bits(&cfg, 0), 0);
        // Release, after the lockout.
        assert_eq!(run(&mut e, &cfg, &[UP, UP], 30), [[0xB0, 103, 0]]);
        assert_eq!(e.led_bits(&cfg, 1), 0);
    }

    #[test]
    fn single_scan_glitch_ignored() {
        let cfg = Config::default();
        let mut e = engine(&cfg);
        assert!(run(&mut e, &cfg, &[DOWN], 1).is_empty());
        assert!(run(&mut e, &cfg, &[UP], 5).is_empty());
    }

    #[test]
    fn bounce_is_suppressed() {
        let cfg = Config::default();
        let mut e = engine(&cfg);
        let mut out = run(&mut e, &cfg, &[DOWN], 2);
        // Bounce for 10 scans.
        for k in 0..10 {
            out.extend(run(&mut e, &cfg, &[if k % 2 == 0 { UP } else { DOWN }], 1));
        }
        out.extend(run(&mut e, &cfg, &[DOWN], 30));
        assert_eq!(out, [[0xB0, 102, 127]]);
    }

    #[test]
    fn latch_toggles() {
        let mut cfg = Config::default();
        cfg.pedals[0].mode = Mode::Latch;
        cfg.pedals[0].color = Color::Green;
        cfg.pedals[0].message = Message::Note { channel: 0, note: 60, velocity: 100 };
        let mut e = engine(&cfg);
        let press = |e: &mut Engine| {
            let mut out = run(e, &cfg, &[DOWN], 30);
            out.extend(run(e, &cfg, &[UP], 30));
            out
        };
        assert_eq!(press(&mut e), [[0x90, 60, 100]]);
        assert_eq!(e.led_bits(&cfg, 0), Color::Green.bits());
        assert!(e.states().active & 1 == 1);
        assert_eq!(press(&mut e), [[0x80, 60, 0]]);
        assert_eq!(e.led_bits(&cfg, 0), 0);
    }

    #[test]
    fn short_tap_still_releases() {
        // Released before the lockout ends: the release is applied when the lockout ends.
        let cfg = Config::default();
        let mut e = engine(&cfg);
        let mut out = run(&mut e, &cfg, &[DOWN], 3);
        out.extend(run(&mut e, &cfg, &[UP], 30));
        assert_eq!(out, [[0xB0, 102, 127], [0xB0, 102, 0]]);
    }

    #[test]
    fn unplugging_releases_held_pedal() {
        let cfg = Config::default();
        let mut e = engine(&cfg);
        run(&mut e, &cfg, &[UP, DOWN], 30);
        assert_eq!(e.connected(), 2);
        assert_eq!(run(&mut e, &cfg, &[UP, 0], 30), [[0xB0, 103, 0]]);
        assert_eq!(e.connected(), 1);
    }

    #[test]
    fn switch_down_at_power_on_is_ignored() {
        let cfg = Config::default();
        let mut e = Engine::new();
        assert!(run(&mut e, &cfg, &[DOWN], 30).is_empty());
        assert!(run(&mut e, &cfg, &[UP], 30).is_empty());
        assert_eq!(run(&mut e, &cfg, &[DOWN], 30), [[0xB0, 102, 127]]);
    }

    #[test]
    fn inverting_does_not_fire_every_pedal() {
        let mut cfg = Config::default();
        let mut e = engine(&cfg);
        cfg.settings.invert_switches = true;
        e.resync();
        assert!(run(&mut e, &cfg, &[UP, UP, UP], 30).is_empty());
        assert_eq!(e.states().pressed, 0b111);
        // Now "UP" means pressed: lifting it is a release, putting it back down a press.
        assert!(run(&mut e, &cfg, &[DOWN, UP, UP], 30).is_empty());
        assert_eq!(run(&mut e, &cfg, &[UP, UP, UP], 30), [[0xB0, 102, 127]]);
    }

    #[test]
    fn release_before_config_change() {
        let mut cfg = Config::default();
        cfg.pedals[0].mode = Mode::Latch;
        let mut e = engine(&cfg);
        run(&mut e, &cfg, &[DOWN], 30);
        run(&mut e, &cfg, &[UP], 30);
        let mut out = Vec::new();
        e.release(0, &cfg.pedals[0], |m| out.push(m.as_bytes().to_vec()));
        assert_eq!(out, [[0xB0, 102, 0]]);
        assert_eq!(e.states().active, 0);
    }
}
