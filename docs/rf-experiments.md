# RF message preparation

The Camera feed RF message panel provides a UTF-8 payload dry run. It does **not** transmit, generate a modulated waveform, or verify reception. All hardware profiles are locked on the server; changing the dropdown or calling the API directly cannot enable RF output. Both existing receivers remain unchanged.

Profiles: Simulation / dry run, Shielded bench test, Ham — Technician, Ham — General, Ham — Amateur Extra, and Experimental authorization. Shielded means real RF contained by a verified test arrangement, not a software smoke test. There is no generic unlicensed HackRF profile. Selecting a license class does not establish a control operator or authority.

## Required before hardware implementation/activation

The station operator must supply the callsign and applicable privileges or experimental grant; approved frequency/channel, emission and occupied bandwidth; antenna/filter/attenuator arrangement; measured output limits; and control arrangements. Enforce an explicit station allowlist, not the whole receive sweep. The 1590–1610 MHz receive window is within radionavigation spectrum and is not an amateur transmit profile. Software limits alone do not verify spectral purity or RF containment.

Next hardware work must implement finite transmissions with a timeout and emergency stop, callsign identification, rate limits, exclusive device ownership, receiver restoration on success/failure, and experiment logs on external storage. Do not add a configuration flag that bypasses these requirements. Shielded operation also needs hardware validation. No unattended transmissions or automatic transmission on detections.

Sources: https://www.arrl.org/frequency-bands ; https://www.arrl.org/band-plan ; https://www.ntia.gov/files/ntia/publications/compendium/1559.00-1610.00_01MAR14.pdf

## Preset channel

The three ham profiles propose 441.500 MHz, listed as “any digital” in the Northern California Packet Association digital band plan: https://ncpa.n0ary.org/bandplan/digital_db.php . The shielded profile uses the same proposed center for repeatable bench comparison. This is an operator-review default, not a determination that the channel is clear or that emissions are compliant. Class selection cannot increase power or unlock hardware. Experimental authorization has no generic default because its grant controls the allowed channel. Simulation has no RF frequency. No frequency entry is exposed in the everyday camera controls.
