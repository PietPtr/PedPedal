// Tests for picoboot.js against a simulated RP2040 bootrom (the PICOBOOT side of it).
// Run: node --test site/config/

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Picoboot, PicobootError, parseUf2 } from "./picoboot.js";

const FLASH = 0x10000000;
const SIZE = 2 * 1024 * 1024;

/** A fake WebUSB device that behaves like the bootrom's PICOBOOT interface. */
class FakeBootrom {
  constructor() {
    this.vendorId = 0x2e8a;
    this.productId = 0x0003;
    this.flash = new Uint8Array(SIZE).fill(0x5a); // old contents
    this.xip = true;
    this.exclusive = 0;
    this.rebooted = false;
    this.log = [];
    this.pending = null; // command waiting for its data or status phase
    this.stalled = false;
    this.lastStatus = 0;
    this.configuration = null;
  }
  async open() {}
  async close() {}
  async selectConfiguration() {
    this.configuration = {
      interfaces: [
        { interfaceNumber: 0, alternates: [{ interfaceClass: 0x08, endpoints: [] }] },
        {
          interfaceNumber: 1,
          alternates: [{
            interfaceClass: 0xff,
            endpoints: [{ direction: "out", endpointNumber: 3 }, { direction: "in", endpointNumber: 4 }],
          }],
        },
      ],
    };
  }
  async claimInterface(n) { assert.equal(n, 1); }
  async controlTransferOut(setup) {
    assert.equal(setup.request, 0x41);
    this.pending = null;
    this.stalled = false;
    return { status: "ok" };
  }
  async controlTransferIn(setup) {
    assert.equal(setup.request, 0x42);
    const dv = new DataView(new ArrayBuffer(16));
    dv.setUint32(4, this.lastStatus, true);
    return { status: "ok", data: dv };
  }
  fail(code) {
    this.lastStatus = code;
    this.stalled = true;
    this.pending = null;
    return { status: "stall" };
  }
  async transferOut(ep, buf) {
    assert.equal(ep, 3);
    if (this.stalled) return { status: "stall" };
    const bytes = new Uint8Array(buf.buffer ?? buf, buf.byteOffset ?? 0, buf.byteLength);
    const p = this.pending;
    if (!p) return this.startCommand(bytes);
    if (p.phase === "data") {
      assert.equal(bytes.length, p.len);
      const err = this.doWrite(p.args[0], bytes);
      if (err) return this.fail(err);
      p.phase = "status";
      return { status: "ok" };
    }
    // status phase of an IN command
    assert.ok(p.id & 0x80 && bytes.length === 0, "expected ZLP status");
    this.pending = null;
    return { status: "ok" };
  }
  async transferIn(ep, length) {
    assert.equal(ep, 4);
    if (this.stalled) return { status: "stall" };
    const p = this.pending;
    assert.ok(p, "transferIn without a command");
    if (p.id & 0x80 && p.phase === "data") {
      const [addr, size] = p.args;
      assert.equal(length, size);
      assert.ok(this.xip, "read with XIP off returns garbage");
      const off = addr - FLASH;
      p.phase = "status";
      const out = new Uint8Array(size + 8);
      out.set(this.flash.subarray(off, off + size), 8);
      return { status: "ok", data: new DataView(out.buffer, 8, size) };
    }
    assert.equal(p.phase, "status");
    this.pending = null;
    return { status: "ok", data: new DataView(new ArrayBuffer(0)) };
  }
  startCommand(b) {
    const v = new DataView(b.buffer, b.byteOffset, 32);
    assert.equal(b.length, 32);
    assert.equal(v.getUint32(0, true), 0x431fd10b);
    const id = v.getUint8(8);
    const argBytes = v.getUint8(9);
    const len = v.getUint32(12, true);
    const args = [0, 1, 2, 3].map((i) => v.getUint32(16 + 4 * i, true));
    this.log.push(id);
    const sizes = { 0x01: 1, 0x02: 12, 0x03: 8, 0x84: 8, 0x05: 8, 0x06: 0, 0x07: 0 };
    if (!(id in sizes)) return this.fail(1);
    if (sizes[id] !== argBytes) return this.fail(2);
    this.lastStatus = 0;
    switch (id) {
      case 0x01: this.exclusive = args[0] & 0xff; break;
      case 0x06: this.xip = false; break;
      case 0x07: this.xip = true; break;
      case 0x02: this.rebooted = true; break;
      case 0x03: {
        const [addr, size] = args;
        if (addr % 4096 || size % 4096) return this.fail(5);
        if (this.xip) return this.fail(8);
        this.flash.fill(0xff, addr - FLASH, addr - FLASH + size);
        break;
      }
      case 0x05: case 0x84:
        if (len !== args[1]) return this.fail(3);
        break;
    }
    this.pending = { id, args, len, phase: len ? "data" : "status" };
    return { status: "ok" };
  }
  doWrite(addr, bytes) {
    if (addr % 256 || bytes.length % 256) return 5;
    if (this.xip) return 8;
    const off = addr - FLASH;
    for (let i = 0; i < bytes.length; i++) this.flash[off + i] &= bytes[i]; // NOR: only clears bits
    return 0;
  }
}

/** Builds a UF2 file from [addr, Uint8Array] pieces, 256 bytes per block like elf2uf2. */
function makeUf2(pieces, family = 0xe48bff56) {
  const blocks = [];
  for (const [addr, data] of pieces) {
    for (let i = 0; i < data.length; i += 256) blocks.push([addr + i, data.subarray(i, i + 256)]);
  }
  const out = new Uint8Array(blocks.length * 512);
  blocks.forEach(([addr, d], n) => {
    const v = new DataView(out.buffer, n * 512, 512);
    v.setUint32(0, 0x0a324655, true);
    v.setUint32(4, 0x9e5d5157, true);
    v.setUint32(8, 0x2000, true);
    v.setUint32(12, addr, true);
    v.setUint32(16, d.length, true);
    v.setUint32(20, n, true);
    v.setUint32(24, blocks.length, true);
    v.setUint32(28, family, true);
    out.set(d, n * 512 + 32);
    v.setUint32(508, 0x0ab16f30, true);
  });
  return out;
}

const random = (n, seed = 1) => {
  const a = new Uint8Array(n);
  for (let i = 0; i < n; i++) a[i] = (seed = (seed * 1103515245 + 12345) >>> 0) >>> 24;
  return a;
};

test("parseUf2 groups blocks into 4 KiB sectors and pads with 0xFF", () => {
  const a = random(5000);
  const sectors = parseUf2(makeUf2([[FLASH, a.subarray(0, 4864)], [FLASH + 0x20000, a.subarray(0, 256)]]));
  assert.deepEqual(sectors.map((s) => s.addr), [FLASH, FLASH + 4096, FLASH + 0x20000]);
  assert.deepEqual(sectors[0].data, a.subarray(0, 4096));
  assert.deepEqual(sectors[1].data.subarray(0, 768), a.subarray(4096, 4864));
  assert.ok(sectors[1].data.subarray(768).every((b) => b === 0xff));
});

test("parseUf2 refuses other chips, the config sector and junk", () => {
  assert.throws(() => parseUf2(makeUf2([[FLASH, random(256)]], 0xe48bff59)), /not for an RP2040/);
  assert.throws(() => parseUf2(makeUf2([[FLASH + SIZE - 4096, random(256)]])), /outside/);
  assert.throws(() => parseUf2(new Uint8Array(512)), /Not a UF2/);
});

test("parseUf2 reads the shipped firmware", () => {
  const uf2 = readFileSync(new URL("./firmware/footswitch.uf2", import.meta.url));
  const sectors = parseUf2(uf2);
  assert.equal(sectors[0].addr, FLASH);
  assert.ok(sectors.at(-1).addr < FLASH + SIZE - 4096);
});

test("flash writes, verifies and reboots, keeping the config sector", async () => {
  const dev = new FakeBootrom();
  const config = random(4096, 7);
  dev.flash.set(config, SIZE - 4096);
  const image = random(10000, 3);
  const sectors = parseUf2(makeUf2([[FLASH, image.subarray(0, 9984)]]));
  const pb = new Picoboot(dev);
  await pb.open();
  const phases = new Set();
  await pb.flash(sectors, (p) => phases.add(p));
  assert.deepEqual(dev.flash.subarray(0, 9984), image.subarray(0, 9984));
  assert.ok(dev.flash.subarray(9984, 3 * 4096).every((b) => b === 0xff));
  assert.equal(dev.flash[3 * 4096], 0x5a); // past the image: untouched
  assert.deepEqual(dev.flash.subarray(SIZE - 4096), config);
  assert.ok(dev.rebooted);
  assert.equal(dev.exclusive, 1);
  assert.deepEqual([...phases], ["write", "verify", "reboot"]);
});

test("a failed check is reported and does not reboot", async () => {
  const dev = new FakeBootrom();
  const orig = dev.doWrite.bind(dev);
  dev.doWrite = (addr, bytes) => { const r = orig(addr, bytes); dev.flash[addr - FLASH + 5] ^= 1; return r; };
  const pb = new Picoboot(dev);
  await pb.open();
  await assert.rejects(pb.flash(parseUf2(makeUf2([[FLASH, random(4096)]]))), (e) => e instanceof PicobootError && e.kind === "verify");
  assert.ok(!dev.rebooted);
  assert.equal(dev.exclusive, 0);
});

test("a stalled command reports the bootrom's status", async () => {
  const dev = new FakeBootrom();
  const pb = new Picoboot(dev);
  await pb.open();
  await assert.rejects(pb.erase(FLASH + 100, 4096), /bad alignment/); // XIP still on, but alignment fails first
  await pb.exitXip(); // the interface works again after the reset
});
