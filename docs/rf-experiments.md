# Supervised RF messages

The private Camera feed has an **RF message** modal. Operator setup, preset choice, dry run, Arm/Disarm, Transmit, and Stop are all in the UI. The public/onion service exposes neither control endpoints nor the modal.

## Supported operation

This release implements International Morse/CW at 20 WPM on a fixed 441.500 MHz preset. Text is uppercased and supports letters, digits, spaces and `. , ? / = -`. The transmitted sequence ends with `DE <station callsign>`. Maximum message length is 64 characters; messages whose full identification plus message exceed 30 seconds are rejected. Binary strings may be entered as text; arbitrary UTF-8 RF modulation is not implemented.

The Northern California Packet Association lists 441.50 MHz for “any digital”: https://ncpa.n0ary.org/bandplan/digital_db.php . Technician, General and Amateur Extra share this supported channel; the dropdown does not unlock their entire frequency allocations. Local use, authorization, emissions and hardware suitability still require operator verification. The 1590–1610 MHz receive window is not a TX preset.

Simulation plans the same waveform and timing without touching hardware. Before setup, it uses a visibly identified N0CALL placeholder; real transmission cannot use that placeholder automatically. Shielded mode emits actual RF and requires a saved shielding confirmation. Experimental-grant mode is displayed but cannot arm this implementation; arbitrary grant-specific frequencies are not supported.

## One-time UI setup

Save the station callsign, operator license class, TX radio, measured conducted output, RF-chain notes and operator acknowledgments. The preset fixes TX VGA gain at 0 dB, RF amplifier off, bias tee off, IQ amplitude 24/127, 8 MS/s, 1.75 MHz hardware baseband filtering and 5 ms shaped key edges. Output is offset 100 kHz above the LO; the physical chain must meet emission requirements including LO leakage. A gain value is not calibrated power. The entered measured conducted output must be at or below the application's 0 dBm ceiling, measured with this exact setup. This declaration is not a software power measurement or legal certification.

Set a 12+ character operator passphrase. It is salted/PBKDF2-hashed on the external drive, never returned by the API or included in worker jobs. Updating setup requires the current passphrase. Operator responsibility acknowledgment version and time are recorded. No config-file editing is needed.

## Per-session control

The operator selects the matching saved ham profile (or verified shielded mode), enters the passphrase, confirms supervision/channel checks, then toggles **Arm transmitter**. Each arm permits one finite burst, expires after 60 seconds and requires browser heartbeats. Closing the modal disarms. Explicit Stop or Disarm terminates active output; heartbeat loss stops output after roughly six seconds. Reloading the service starts disarmed. There is a 60-second attempt cooldown. There are no automatic retries, repeat transmissions or automatic detection-triggered RF actions.

A separate watchdog worker holds an exclusive lock, creates temporary IQ only on external storage, stops just the selected receive service, transmits with an explicit sample count, and restores that receive service in a finally block. The other HackRF keeps receiving. Transfer success does not establish reception or decoding. Worker metadata includes text, timing, identity, frequency, declared measured power and outcome; temporary waveform/job/log files are deleted afterward. Restoration failures are reported rather than hidden. The finite file/sample count also bounds RF duration if the worker itself is forcibly killed.

## Responsibility and verification

Live RF is for licensed, authorized operators. They are responsible for permitted frequencies, emissions, power, identification, and avoiding harmful interference. Unauthorized operation can result in fines, equipment seizure or other penalties. Software presets and disclaimers do not confer authorization, certify compliance or guarantee liability protection. Public-release legal terms require legal review.

Sources:
- FCC Part 97: https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97
- FCC enforcement example: https://docs.fcc.gov/public/attachments/DOC-357562A1.pdf
- Local digital band plan: https://ncpa.n0ary.org/bandplan/digital_db.php
- HackRF filtering guidance: https://hackrf.readthedocs.io/en/stable/sampling_rate.html

Validation uses waveform frequency/envelope measurements and mocked hardware for authentication, fixed command limits, one-shot protection, heartbeat expiry, failure cleanup and RX restoration. No over-the-air hardware validation has been performed by the software agent. The deployed station remains unconfigured and disarmed until its operator completes setup.
