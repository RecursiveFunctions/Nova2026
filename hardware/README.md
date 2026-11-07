# Smart Pickup Box: hardware (Person C)

One box = Raspberry Pi 3/4 + 3.5" 480x320 LCD (HannStar HSD035577B5 panel) + 2-wire DC motor
latch + a QR code. `bridge.py` runs on the Pi and only mirrors the backend:

| Box state | LCD shows | Latch |
|---|---|---|
| AVAILABLE | "Available" | unlocked |
| PREPARING | items and quantities only | unlocked (staff load the food) |
| READY | order ID, short name, summary, **QR code** | **locked** |
| UNLOCKED (code accepted) | "Pickup authorized" | unlocked |

There is no RFID reader. **One QR code per box** opens `http://<laptop-IP>:5173/pickup/BOX-01`:

- while the order is **PREPARING**, staff scan it and enter their **staff ID** -> READY and the latch locks;
- once it is **READY**, the courier scans it (sticker or the QR on the LCD) and enters the one-time
  code from the courier dashboard -> the latch opens;
- the supervised **Complete pickup** button on `/simulator` (or `bridge.py --simulate-complete`) then
  frees the box for the next order.

Staff IDs live in `backend/.env` (`STAFF_RFID_UIDS`, comma separated; the name stayed for the API
contract) or are added on `/courier`. Anyone can open the QR page, so use IDs that are hard to guess.

## 1. Pi setup (about 20 minutes)

1. Flash **Raspberry Pi OS (Bookworm)** with Raspberry Pi Imager; set Wi-Fi (the demo network), SSH
   and user `pi` in the Imager settings. Desktop is not needed (Lite is fine).
2. Packages and the code:
   ```bash
   sudo apt update && sudo apt install -y python3-pil python3-qrcode python3-gpiozero git
   git clone -b keyaan https://github.com/RecursiveFunctions/Nova2026.git ~/Nova
   ```
3. **LCD driver.** HSD035577B5 panels come on the common "3.5inch RPi LCD" boards (ILI9486 driver chip,
   SPI, 26-pin header). Add this to the end of `/boot/firmware/config.txt` and reboot:
   ```
   dtparam=spi=on
   dtoverlay=piscreen,speed=16000000,rotate=90
   ```
   Check with `ls /dev/fb*`: **`/dev/fb1` must exist**. Test it:
   `cat /dev/urandom | sudo tee /dev/fb1 > /dev/null` (the screen fills with noise; Ctrl+C).
   - Screen stays white: try `dtoverlay=waveshare35a` instead (download `waveshare35a.dtbo` from the
     Waveshare LCD-show repo into `/boot/firmware/overlays/`), or check the board's printed model.
   - Colours look wrong or image is mirrored: change `rotate=` (0/90/180/270) or use `ROTATE` below.
   - The bridge draws directly on `/dev/fb1`, so you do **not** need LCD-show or a desktop.
4. Settings: `cd ~/Nova/hardware && cp bridge.env.example bridge.env && nano bridge.env`
   (set `BOX_ID`, the laptop's LAN IP in `API_BASE_URL` and `PUBLIC_URL`).
5. First run, screen only: `set -a; . ./bridge.env; set +a; python3 bridge.py --lock none`.
   Create an order on `/simulator`: the LCD should switch to PREPARING within a second.

## 2. Motor latch wiring

**Never connect the motor to the Pi directly** (GPIO pins give ~16 mA; the motor needs hundreds, and
its back-EMF can kill the Pi). Use an H-bridge board: L298N, L9110S, TB6612FNG or DRV8833.

The LCD board covers physical pins 1-26, so use the free pins 27-40:

| H-bridge pin | Pi (physical pin / BCM) |
|---|---|
| IN1 | pin 29 / GPIO5 |
| IN2 | pin 31 / GPIO6 |
| ENA (L298N) | leave the ENA jumper on (speed is PWM on IN1/IN2) |
| GND | pin 30, 34 or 39 (**shared ground with the motor battery**) |
| OUT1 / OUT2 | the two motor wires |
| +V / VCC (motor) | separate battery pack, **not** the Pi's 5 V (see below) |

- **L298N:** feed it 7-9 V (6xAA or a 9 V battery) with the 5V-EN jumper on, so its own regulator powers
  its logic; it drops about 2 V, which suits a small gear motor.
- **L9110S / DRV8833:** no ENA pin and no logic supply; power them with a 4xAA pack (6 V).
- **TB6612FNG:** needs a 3.3 V logic supply and STBY/PWMA high, but the LCD covers the Pi's 3.3 V and 5 V
  pins (1-26). Only use it if your LCD board passes those pins through; otherwise pick one of the above.

**Mechanism:** a geared motor (yellow TT or N20) turns an arm or cam that swings into a slot on the door.
`bridge.py` runs the motor forward to lock and backward to unlock for `LOCK_SECONDS` (0.6 s) at
`LOCK_SPEED` (60 %). Put hard stops at both ends of the arm's travel so it never over-rotates, then tune:

```bash
set -a; . ./bridge.env; set +a
python3 bridge.py        # make an order READY (staff ID on the QR page) -> it should lock
```

- Turns the wrong way: swap the two motor wires.
- Doesn't reach the end: raise `LOCK_SECONDS` or `LOCK_SPEED` a little. Stalls loudly: lower them.
- Two micro/limit switches (between a GPIO pin and GND, e.g. GPIO13 = pin 33 and GPIO19 = pin 35) make
  it exact: set `LOCKED_SWITCH` / `UNLOCKED_SWITCH` and the motor stops as soon as the switch closes.
- The bridge only follows the backend: it locks when the order is READY and unlocks only after the
  backend accepted a pickup code. On connection loss it leaves the latch where it is.

## 3. QR codes

The LCD shows the QR when the order is READY. Staff need it while PREPARING, so also print a sticker:

```bash
python make_qr.py --public-url http://<laptop-LAN-IP>:5173      # writes qr-BOX-01.png, qr-BOX-02.png
```

The laptop's IP changes at a new venue: reprint there (the LCD QR follows `PUBLIC_URL`). Never use
`localhost` in a QR code; phones cannot open it.

## 4. Start at boot

```bash
sudo cp pickupbox-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now pickupbox-bridge
journalctl -u pickupbox-bridge -f
```

## Testing without a Pi

```bash
pip install pillow qrcode
python bridge.py --box BOX-01 --display png --lock none --public-url http://<laptop-IP>:5173
```

writes `screen-BOX-01.png` every time the state changes. One-shot events:
`--simulate-staff-ready --staff-id <id>` and `--simulate-complete`.

## Demo checklist (sheet tests)

- T5: staff ID on the QR page -> LCD shows pickup details, latch locks.
- T6: wrong staff ID -> refused, nothing changes.
- T8: QR opens the right box's page on a real phone.
- T9/T10: wrong pickup code -> stays locked; right code -> latch opens.
- T13: second "mark ready" -> no change, no new code.
- T14: unplug the Pi's network -> LCD shows "Connection lost", latch stays, nothing is marked collected.
