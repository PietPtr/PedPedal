//! Shared code for the footswitch firmware and its host driver.
//!
//! - [`config`]: what each pedal does (MIDI message, momentary/latch, LED colour), and how the
//!   config is stored in flash.
//! - [`protocol`]: the SysEx request/response format the driver uses to configure the device.
//! - [`usb`]: USB-MIDI event packets (4 bytes each) to and from MIDI byte streams.
//! - [`engine`]: the pedal state machine: debouncing, momentary/latch, LED state and the MIDI
//!   messages to send.
//!
//! Everything is `no_std` and allocation-free, so the firmware uses it as-is and it can be unit
//! tested on the host.
#![no_std]

#[cfg(test)]
extern crate std;

pub mod config;
pub mod engine;
pub mod protocol;
pub mod usb;

pub use config::{Color, Config, Message, Mode, PedalConfig, Settings};

/// The most pedals (modules) the firmware scans. More modules than this are ignored.
pub const MAX_PEDALS: usize = 16;

/// A MIDI channel message of 2 or 3 bytes, ready to send.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ShortMessage {
    bytes: [u8; 3],
    len: u8,
}

impl ShortMessage {
    pub const fn new3(status: u8, d1: u8, d2: u8) -> Self {
        Self { bytes: [status, d1 & 0x7F, d2 & 0x7F], len: 3 }
    }

    pub const fn new2(status: u8, d1: u8) -> Self {
        Self { bytes: [status, d1 & 0x7F, 0], len: 2 }
    }

    /// The message bytes (status byte first).
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes[..self.len as usize]
    }

    pub fn status(&self) -> u8 {
        self.bytes[0]
    }
}
