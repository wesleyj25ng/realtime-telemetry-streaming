# Real-Time Telemetry & Streaming (CCSDS-Style) — Demo

This repo is a **public, sanitized demo** showing systems concepts related to packetized telemetry streaming and protocol debugging.

It includes:
- a Python UDP demo that packetizes payload data into **CCSDS-style segments**
- a Wireshark Lua dissector **example** that shows how to decode a CCSDS-style header and map message IDs to fields

This repository is **not** a dump of internship code. It is a **generic recreation** intended to demonstrate the same technical ideas (packet framing, segmentation, UDP transport, and tooling for debugging binary protocols).

## Contents

- udp/ - UDP sender/receiver + CCSDS-style packet framing demo
- wireshark/ - Wireshark Lua dissector example for decoding packets

## What this demonstrates
- UDP streaming and best-effort transport
- packet framing, segmentation, and sequence numbers
- binary parsing and endianness awareness
- debugging workflows using Wireshark + custom dissectors

## Notes
Any proprietary identifiers, internal schemas, and hardware-specific dependencies have been removed. This repo is intended as a **conceptual demo** for public sharing.
