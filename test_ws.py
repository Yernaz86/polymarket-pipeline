#!/usr/bin/env python3
"""
Manual WebSocket test for Polymarket price feed.

Usage:
    python test_ws.py                          # listen for any broadcast messages
    python test_ws.py <condition_id> [...]     # subscribe to specific markets

Example condition_id (grab from gamma-api.polymarket.com/markets):
    python test_ws.py 0x1234abcd...

The script connects for 60 seconds and prints every message it receives.
Press Ctrl+C to stop early.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
LISTEN_SECONDS = 60


async def test(condition_ids: list[str]) -> None:
    try:
        import websockets
    except ImportError:
        print("ERROR: websockets not installed. Run: pip install websockets")
        return

    print(f"Connecting to {WS_URL} ...")
    try:
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=15,
        ) as ws:
            print("Connected!\n")

            # Subscribe to markets if provided
            if condition_ids:
                for cid in condition_ids:
                    sub = {"type": "subscribe", "channel": "price", "market": cid}
                    await ws.send(json.dumps(sub))
                    print(f"  Subscribed: {cid}")
                print()
            else:
                print("  No condition IDs given — waiting for broadcast messages\n")

            print(f"Listening for {LISTEN_SECONDS}s (Ctrl+C to stop)...\n")
            deadline = time.monotonic() + LISTEN_SECONDS
            count = 0

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(5.0, remaining))
                except asyncio.TimeoutError:
                    print("  (no message in last 5s — connection still alive)")
                    continue

                count += 1
                # Decode bytes if needed
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        print(f"[msg {count}] <binary frame, {len(raw)} bytes>")
                        continue

                # Skip plain keepalive strings
                if raw.strip().upper() in ("PING", "PONG", ""):
                    print(f"[msg {count}] <keepalive: {raw.strip()!r}>")
                    continue

                # Pretty-print JSON
                try:
                    data = json.loads(raw)
                    formatted = json.dumps(data, indent=2)
                    print(f"[msg {count}]\n{formatted}\n")
                except json.JSONDecodeError:
                    print(f"[msg {count}] RAW: {raw!r}\n")

    except OSError as e:
        print(f"Connection failed: {e}")
        return

    print(f"Done. Received {count} messages in {LISTEN_SECONDS}s.")
    if count == 0 and condition_ids:
        print(
            "\nNo messages received. Possible reasons:\n"
            "  1. The condition_id format may be wrong (try the token_id instead)\n"
            "  2. No price activity on this market right now\n"
            "  3. The subscription channel name may have changed\n"
            "  Tip: run without a condition_id first to see what the server broadcasts."
        )


if __name__ == "__main__":
    try:
        asyncio.run(test(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nStopped.")
