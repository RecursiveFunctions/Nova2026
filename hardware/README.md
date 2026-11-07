# Smart Pickup Box: hardware bridge (Person C)

`bridge.py` connects one physical box to the backend. Standard library only (`pyserial` just for a
serial RFID reader). Set the backend address once:

```bash
export API_BASE_URL=http://<API-laptop-LAN-IP>:8000      # Windows PowerShell: $env:API_BASE_URL="http://..."
```

| Command | What it does |
|---|---|
| `python bridge.py --box BOX-01 --simulate-staff-tap` | One staff tap with `STAFF-TAG-01` (or `--uid ...`). Box PREPARING -> READY. |
| `python bridge.py --box BOX-01 --simulate-complete` | Supervised "food was taken": order COLLECTED, box takes the next order. |
| `python bridge.py --box BOX-01 --watch` | Polls the box every second; prints the screen text and drives the lock from `lock_state`. |
| `python bridge.py --box BOX-01 --rfid stdin` | USB RFID readers that act as a keyboard: each scanned UID + Enter is a staff tap. Also runs `--watch`. |
| `python bridge.py --box BOX-01 --rfid serial:COM3:9600` | Microcontroller printing one UID per line over serial (`pip install pyserial`). Also runs `--watch`. |

Repeat reads of the same card within 3 seconds are ignored (card left on the reader).

## Wiring it to the real parts

- **Lock:** fill in `Lock.engage()` / `Lock.release()`. The bridge only follows the backend
  (`LOCKED` while READY, released after a valid code); it never unlocks by itself.
- **Display:** if the screen can run a browser, open `http://<LAN-IP>:5173/screen/BOX-01` instead.
  Otherwise fill in `Display.show()`; `screen_lines()` already gives the rows for each state
  (items only while preparing, no pickup code ever).
- **Door sensor (optional):** when the door closes after an `UNLOCKED` state, call
  `api.complete_pickup()`. Without a sensor, use `--simulate-complete` or the supervised button on
  the simulator page.
- **Unknown card:** the backend log prints its UID; register it on the frontend's `/courier` page or
  with `POST /demo/staff`.

## NFC tags

Write `http://<API-laptop-LAN-IP>:5173/pickup/BOX-01` (and `BOX-02`). Never `localhost`. If tags cannot
be written, print a QR code with the same URL.
