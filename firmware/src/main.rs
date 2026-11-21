//! Footswitch firmware for the Raspberry Pi Pico on module 1.
//!
//! - Scans the module chain every millisecond (see `chain.rs`).
//! - Sends each pedal's MIDI message over USB MIDI, in momentary or latch mode.
//! - Lights each pedal's LED in its colour while the pedal is on.
//! - Takes configuration as SysEx on the same USB MIDI port (see `footswitch_core::protocol`),
//!   and keeps it in flash (see `storage.rs`).
//!
//! Started from <https://github.com/rp-rs/rp2040-project-template>.
#![no_std]
#![no_main]

mod chain;
mod storage;

use defmt::{info, warn};
use defmt_rtt as _;
use embedded_hal::digital::OutputPin;
use heapless::Deque;
use panic_probe as _;

use rp2040_hal::{self as hal, Clock, entry, pac};
use usb_device::class_prelude::UsbBusAllocator;
use usb_device::prelude::*;
use usbd_midi::UsbMidiClass;

use footswitch_core::engine::{Engine, SCAN_INTERVAL_US};
use footswitch_core::protocol::{
    self, DeviceInfo, PROTOCOL_VERSION, Request, RequestError, Response, Status,
};
use footswitch_core::usb::{SysexAssembler, short_message_packet, sysex_packets};
use footswitch_core::{Config, MAX_PEDALS, ShortMessage};

/// Second-stage bootloader for the Pico's W25Q080 flash.
#[unsafe(link_section = ".boot2")]
#[used]
pub static BOOT2: [u8; 256] = rp2040_boot2::BOOT_LOADER_W25Q080;

const XTAL_FREQ_HZ: u32 = 12_000_000;

/// pid.codes / V-USB shared VID:PID for MIDI devices (VOTI, "free shared PID for MIDI
/// class devices"). Hosts tell devices apart by the product string.
const USB_VID_PID: UsbVidPid = UsbVidPid(0x16C0, 0x05E4);
const USB_PRODUCT: &str = "Footswitch";

const FIRMWARE_VERSION: [u8; 3] = [
    parse_u8(env!("CARGO_PKG_VERSION_MAJOR")),
    parse_u8(env!("CARGO_PKG_VERSION_MINOR")),
    parse_u8(env!("CARGO_PKG_VERSION_PATCH")),
];

/// USB-MIDI packets waiting to go out. A reply is at most 8 packets.
const TX_QUEUE: usize = 64;
/// Drop queued packets the host hasn't taken for this long (µs).
const STALE_US: u64 = 500_000;

#[entry]
fn main() -> ! {
    info!("footswitch firmware start");
    let mut pac = pac::Peripherals::take().unwrap();
    let mut watchdog = hal::Watchdog::new(pac.WATCHDOG);
    let sio = hal::Sio::new(pac.SIO);

    let clocks = hal::clocks::init_clocks_and_plls(
        XTAL_FREQ_HZ,
        pac.XOSC,
        pac.CLOCKS,
        pac.PLL_SYS,
        pac.PLL_USB,
        &mut pac.RESETS,
        &mut watchdog,
    )
    .ok()
    .unwrap();
    info!("system clock {} Hz", clocks.system_clock.freq().to_Hz());

    let timer = hal::Timer::new(pac.TIMER, &mut pac.RESETS, &clocks);
    let pins = hal::gpio::Pins::new(pac.IO_BANK0, pac.PADS_BANK0, sio.gpio_bank0, &mut pac.RESETS);

    // The Pico's own LED (GP25): on while the USB host has configured the device.
    let mut status_led = pins.gpio25.into_push_pull_output();

    let mut chain = chain::Chain::new(
        pac.PIO0,
        &mut pac.RESETS,
        (
            pins.gpio16.into_function().into_pull_type(),
            pins.gpio17.into_function().into_pull_type(),
            pins.gpio18.into_function().into_pull_type(),
            pins.gpio19.into_function().into_pull_type(),
        ),
    );

    let usb_bus = UsbBusAllocator::new(hal::usb::UsbBus::new(
        pac.USBCTRL_REGS,
        pac.USBCTRL_DPRAM,
        clocks.usb_clock,
        true,
        &mut pac.RESETS,
    ));
    let mut midi = UsbMidiClass::new(&usb_bus, 1, 1).unwrap();
    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, USB_VID_PID)
        .strings(&[StringDescriptors::default().manufacturer("DIY").product(USB_PRODUCT)])
        .unwrap()
        .device_class(0) // the class is given per interface
        .build();

    let config = storage::load().unwrap_or_else(|| {
        info!("no saved config, using defaults");
        Config::default()
    });
    let mut app = App {
        config,
        engine: Engine::new(),
        tx: Deque::new(),
        reboot_at: None,
    };
    let mut sysex = SysexAssembler::<{ protocol::MAX_MESSAGE_LEN }>::new();

    let mut next_scan = timer.get_counter().ticks();
    // When the host last took a packet (or the queue was last empty).
    let mut last_tx = next_scan;
    loop {
        // USB: receive configuration requests.
        if usb_dev.poll(&mut [&mut midi]) {
            let mut buf = [0u8; 64];
            if let Ok(n) = midi.read(&mut buf) {
                for p in buf[..n].as_chunks::<4>().0 {
                    if let Some(msg) = sysex.push_packet(*p) {
                        let now = timer.get_counter().ticks();
                        app.handle_sysex(msg, now);
                    }
                }
            }
        }

        // USB: send queued MIDI. Without a host, drop it instead of piling it up.
        let now = timer.get_counter().ticks();
        let configured = usb_dev.state() == UsbDeviceState::Configured;
        if configured {
            while let Some(p) = app.tx.front() {
                match midi.send_bytes(*p) {
                    Ok(_) => {
                        app.tx.pop_front();
                        last_tx = now;
                    }
                    Err(_) => break, // endpoint busy; try again next time round
                }
            }
            // The host only reads the endpoint while some program has the port open. Don't
            // hand stale presses to the next program that opens it.
            if app.tx.is_empty() {
                last_tx = now;
            } else if now - last_tx > STALE_US {
                warn!("host not reading, dropping {} queued packets", app.tx.len());
                app.tx.clear();
            }
        } else {
            app.tx.clear();
        }
        let _ = status_led.set_state(configured.into());

        if now >= next_scan {
            next_scan += SCAN_INTERVAL_US as u64;
            if next_scan < now {
                // We fell behind (e.g. while saving to flash); don't try to catch up.
                next_scan = now + SCAN_INTERVAL_US as u64;
            }
            let leds = core::array::from_fn(|i| app.engine.led_bits(&app.config, i));
            let switches = chain.scan(&leds);
            app.scan(&switches);
        }

        if let Some(t) = app.reboot_at
            && now >= t
        {
            info!("rebooting into the USB bootloader");
            hal::rom_data::reset_to_usb_boot(0, 0);
        }
    }
}

struct App {
    config: Config,
    engine: Engine,
    tx: Deque<[u8; 4], TX_QUEUE>,
    /// When set, reboot into the bootloader at this timer value (after the reply is sent).
    reboot_at: Option<u64>,
}

impl App {
    fn scan(&mut self, switches: &[u8; MAX_PEDALS]) {
        let before = self.engine.connected();
        let tx = &mut self.tx;
        self.engine.scan(&self.config, switches, |m| enqueue_message(tx, m));
        let after = self.engine.connected();
        if after != before {
            info!("{} module(s) connected", after);
        }
    }

    fn handle_sysex(&mut self, msg: &[u8], now: u64) {
        let (command, result) = match Request::decode(msg) {
            Ok(req) => (req.command() as u8, self.handle(req, now)),
            Err(RequestError::NotOurs) => return,
            Err(RequestError::Invalid { command, status }) => (command, Err(status)),
        };
        let reply = protocol::encode_response(command, result.as_ref().map_err(|s| *s));
        for p in sysex_packets(reply.as_bytes()) {
            if self.tx.push_back(p).is_err() {
                warn!("tx queue full, reply dropped");
                break;
            }
        }
    }

    fn handle(&mut self, req: Request, now: u64) -> Result<Response, Status> {
        let tx = &mut self.tx;
        let mut send = |m| enqueue_message(tx, m);
        match req {
            Request::GetInfo => Ok(Response::Info(DeviceInfo {
                protocol_version: PROTOCOL_VERSION,
                firmware_version: FIRMWARE_VERSION,
                max_pedals: MAX_PEDALS as u8,
                connected_pedals: self.engine.connected() as u8,
            })),
            Request::GetPedal { index } => {
                let config = *self.config.pedals.get(index as usize).ok_or(Status::BadIndex)?;
                Ok(Response::Pedal { index, config })
            }
            Request::SetPedal { index, config } => {
                let i = index as usize;
                let old = *self.config.pedals.get(i).ok_or(Status::BadIndex)?;
                // Turn the pedal off under its old config, so nothing is left hanging.
                self.engine.release(i, &old, &mut send);
                self.config.pedals[i] = config;
                Ok(Response::Done)
            }
            Request::GetSettings => Ok(Response::Settings(self.config.settings)),
            Request::SetSettings(s) => {
                if s != self.config.settings {
                    self.config.settings = s;
                    self.engine.resync();
                }
                Ok(Response::Done)
            }
            Request::GetState => Ok(Response::State(self.engine.states())),
            Request::Save => {
                info!("saving config");
                storage::save(&self.config).map_err(|_| Status::FlashError)?;
                Ok(Response::Done)
            }
            Request::ResetDefaults => {
                self.engine.release_all(&self.config, &mut send);
                self.config = Config::default();
                self.engine.resync();
                Ok(Response::Done)
            }
            Request::EnterBootloader => {
                // Give the reply 100 ms to get out first.
                self.reboot_at = Some(now + 100_000);
                Ok(Response::Done)
            }
        }
    }
}

fn enqueue_message(tx: &mut Deque<[u8; 4], TX_QUEUE>, m: ShortMessage) {
    if tx.push_back(short_message_packet(&m)).is_err() {
        warn!("tx queue full, MIDI message dropped");
    }
}

const fn parse_u8(s: &str) -> u8 {
    let b = s.as_bytes();
    let mut v = 0u8;
    let mut i = 0;
    while i < b.len() {
        v = v * 10 + (b[i] - b'0');
        i += 1;
    }
    v
}
