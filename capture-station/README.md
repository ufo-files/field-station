# Field Station

Camera and RF experiment dashboard running directly on the Raspberry Pi.

- LAN: <http://192.168.8.208:8090/>
- Tailscale: <http://100.117.92.45:8090/>
- Existing OpenWebRX receiver: <http://100.117.92.45:8073/>

## Use

Connect Canon HDMI → Cam Link → Pi USB. Power the camera on in movie mode,
and verify an actual picture in the dashboard. The Cam Link can deliver fresh
frames containing its own **NO SIGNAL** screen; “Receiving frames” only confirms
the capture device is supplying frames.

Enter a name, condition, notes, and a duration limit, then start a session.
Add event markers during capture. Stop manually or let the duration limit stop
the session. Review a saved session to play video, view the nearest recorded RF
snapshot, jump to markers, or download the original files.

Manual capture conditions are labels. Automatic capture controls actual stimulus
playback: a silent baseline, its frame export, a configured gap, an optional CE5
session, then its frame export. Choose one cycle or repeat on a timed schedule.
The defaults are 3-minute recordings, a 10-minute minimum gap, one cycle every
60 minutes, 60 fps video capture, and export of every recorded frame. CE5 playback is initially off so
silent hourly captures can run before a speaker is connected.
Both conditions record video and approximately one RF snapshot per second.
The original MJPEG camera stream is archived without re-encoding at the configured FPS (60 by default). The supervisor stops capture at the configured duration, allowing buffered data to drain. A confirmed RF event can extend a recording; an independent two-hour cap remains in the capture process.
No microphone track or session media upload is configured.

Under Automatic capture, select a file already in `T7/Uploads` or upload audio
through the dashboard. An excerpt matching the recording duration is prepared as stereo 48 kHz PCM;
short files loop. Selecting audio copies it and preserves the uploaded original.
The supplied Working Group materials identify CD3 as field-work audio. CD3 Track 1
is the initially configured selection; the dashboard can select any uploaded track.

Connect a speaker to the Pi, select its playback device, use the two-second speaker
test, then enable automatic capture. The Canon HDMI port is output-only; its
speaker cannot receive playback through the Cam Link. HDMI device entries can
appear even when no audio display is connected, so playback is validated before
starting. Silent automatic capture requires fresh RF snapshots, a fresh camera feed,
and sufficient SSD space. Checking Include CE5 playback additionally requires
selected audio and usable playback hardware.

Enabled schedules resume after a service restart at the next scheduled cycle;
interrupted pairs are skipped. The run interval is measured between baseline
start times, and the gap is measured from a recording's stop time. The exporter
may use this gap; a new recording waits for both the gap and frame completion.
Missed hours are skipped instead of replayed in a burst. The UI shows the next
scheduled capture, supports saving duration/interval/gap/frame-rate/playback
settings, and applies edits to the next cycle. All-frame export automatically follows video FPS; sampling cannot exceed video FPS. A cycle already underway keeps a
snapshot of its settings in the manifest. The interval must fit the requested
recordings and their minimum gaps. Disabling it stops an active
trial. Stale RF data or failed playback stops the sequence and marks the trial
incomplete. Each CE5 session stores its actual stimulus WAV, hash, output device,
volume setting, and playback request timestamp. Acoustic onset and sound pressure
are not measured. The frame exporter runs after capture and must succeed before
the next automatic trial begins.

## What is recorded

Each directory in `sessions/` contains:

- `video.mkv`: original 1920×1080 MJPEG stream, 60 fps requested by default, copied without re-encoding.
- `video.mp4`: H.264 playback copy made afterward, preserving every recorded frame and its presentation time.
- `capture-progress.txt`: capture frame counters and timing diagnostics.
- `rf.jsonl`: unique fresh snapshots from `/home/hackrf/signal-spool/live.json`,
  approximately once per second, with observer timestamps and elapsed times.
- `manifest.json`: condition, notes, start/stop times, stop reason, markers,
  file sizes and SHA-256 checksums.
- `capture.log`: FFmpeg diagnostics.
- `frames/export-*/frame-000000000.jpg`, etc.: full-resolution JPEGs for every recorded frame by default. Original MJPEG packets are copied byte-for-byte when full export is selected. Older sampled exports remain intact.
- `frames/index.json`: frame filenames, video times, byte counts, SHA-256 hashes.
- `frames.log`: frame-export diagnostics.
- `stimulus.wav` and `playback.log`: stimulus evidence for automatic CE5 trials.

Frame extraction is queued after completed recordings. Every recorded frame is the default; sampled JPEG export must be explicitly selected. Input FPS, export mode, and an optional sampling rate have separate controls. Session review shows its
status and a frame gallery, and can request extraction for older completed videos.
Failed extraction can be retried. Files in progress at restart are requeued.

The station reads the existing RF snapshots. OpenWebRX retains ownership of the
HackRF; the continuous logger and hourly GitHub publishing remain independent.
This records FFT summaries, not raw IQ. The receiver determines the actual RF
coverage; each spectrum snapshot retains its range and measurement fields.

UTC comes from the Pi's synchronized system clock. Elapsed times use the
monotonic clock. Camera capture starts shortly after the session request;
HDMI latency and software startup delay are uncalibrated. Review aligns nearest
RF snapshots to session elapsed time and displays the offset; it does not claim
frame-accurate synchronization.

Recording requires 3 GiB free at start and stops if free space falls below
2 GiB, or at the chosen duration (1–120 minutes). Sessions stay local and are
never automatically deleted. A restarted station marks unfinished sessions
interrupted. Fragmented MP4 improves partial-file recovery, but does not guarantee
that a file interrupted by power loss is playable.

Recordings are stored on the 1 TB Samsung T7 (serial `S6XBNS0W321351N`),
formatted ext4 and mounted at `/home/hackrf/t7` by filesystem UUID. Sessions use
`/home/hackrf/t7/sessions`; the continuous RF spool uses
`/home/hackrf/t7/signal-spool`. The original paths are compatibility symlinks.
Original SD-card data was retained in directories named `sessions.sd-backup-*`
and `signal-spool.sd-backup-*` after verified copying.

The capture service's `storage.conf` drop-in sets `CAPTURE_DATA`,
`CAPTURE_VOLUME`, and `CAPTURE_VOLUME_ID`. A missing mount or mismatched drive
marker blocks new recordings. A drive disconnect during a session stops capture
and saves an interruption report under `run/`. Mount points are protected
against unprivileged writes when the drive is absent, so neither the RF spool
nor the session path silently falls back to the SD card. RF logger and publisher
system-service drop-ins require the SSD mount. Previews and small diagnostic
files remain on the SD card.

## Operations

```sh
systemctl --user status capture-station.service
systemctl --user restart capture-station.service
systemctl --user stop capture-station.service
loginctl show-user hackrf -p Linger
```

The enabled user service is installed at
`~/.config/systemd/user/capture-station.service`. User lingering is enabled so
it starts at boot without an interactive login. Python uses only the standard
library. FFmpeg and Debian/Raspberry Pi dependencies are extracted under
`vendor/root/`; system package installation was not needed.

The app listens on port 8090 on the Pi's network interfaces for LAN/Tailscale
access. It has no application login. Its control endpoints require a per-process
token and reject cross-origin requests. Do not expose it through public port
forwarding. `CAPTURE_BIND`, `CAPTURE_PORT`, and `CAPTURE_DEVICE` can be set in
the service environment; the default camera uses the Cam Link's stable by-ID path.

The web preview refreshes at 2 fps, independent of capture FPS. Preview JPEG packets are copied into `/run/user/1000/field-station/preview.jpg` on RAM-backed storage; they are not repeatedly written to the SD card. Every original camera frame still goes into the recorded archive. Starting or
stopping a session briefly restarts the camera process; only one session records
at a time. Status includes logger freshness, upload timer and last result,
upload journal, receiver state, clock synchronization, disk space, and autostart.

## Validation

`check_station.py` drives the installed ChromeDriver via WebDriver HTTP,
records a labelled short validation session, and checks actual browser controls,
RF snapshots, event markers, checksums, MP4 properties, range requests, session
review, console errors, and mobile overflow. It requires the app and ChromeDriver
on localhost ports 8090 and 9515. It starts a temporary ChromeDriver when needed
and refuses to start if another session is active.
Validation artifacts live in `run/` and the validation recording remains visibly
labelled in the session library.

## iPad SSD access

Samba shares the mounted T7 as `T7`. In iPad Files, use Connect to Server with
`smb://100.117.92.45` over Tailscale or `smb://192.168.8.208` on the local network.
Sign in as registered user `hackrf` with the SMB password set on the Pi.
The share is writable; copy purchased materials into `T7/Uploads`.
Samba uses `fruit streams_xattr` for Apple metadata support. It is restricted to
the local subnet and Tailscale addresses and requires the SSD mount at startup.
`setup-smb.sh` installs and validates this configuration and prompts for an SMB
password when needed. `smb.conf` is its tracked configuration source.

Storage and sequencing checks run with:

```sh
python3 -m unittest test_storage test_experiments -v
```

For a complete one-minute camera/RF/frame-export browser check:

```sh
python3 check_station.py --one-minute
```

## Full-frame integrity and SSD cable

The exporter verifies captured frame counters against exported JPEG count and
MP4 frame count. A mismatch fails processing and stops automatic advancement.
The frame index stores original presentation timestamps and SHA-256 packet hashes.
Native MJPEG frame export copies packet bytes, avoiding a second JPEG compression.
Archive hashes are calculated asynchronously so large files do not block live
status or RF snapshot polling. Recording and frame processing are serialized to
avoid competing SSD writes. Frame galleries use 120-frame pages.

A verified 1080p60 camera test recorded 601 frames in approximately 10 seconds;
export and the playback MP4 each contained all 601 frames. The observed original
stream rate was about 42 MB/s. A USB 3 data cable and blue USB 3 port are appropriate
for this workload; the initial T7 connection negotiated only USB 2 (480 Mb/s).

For a safe cable change, run `sudo python3 swap_t7.py unmount`, wait for
SAFE TO DISCONNECT, then reconnect and run `sudo python3 swap_t7.py resume`.
This pauses recording, stops RF writes and SMB, flushes and unmounts the SSD,
and restores the saved schedule and services after mounting the same T7 again.
The dashboard can remain online while the drive is disconnected.

## Observation-based RF trigger

The RF trigger is independent of the hourly schedule. It monitors fresh 1590–1610
MHz spectrum snapshots at 100 kHz bin resolution. After learning at least 60
fresh snapshots, it compares each bin to the median of its preceding baseline
(default window: 300 snapshots). Detected candidates are excluded from baseline
updates so a sustained event does not immediately become its own background.

A capture starts after two distinct, fresh snapshots confirm either:

- A new peak at least +20 dB (100× nominal power) above the current spatial
  noise-floor estimate **and** +10 dB (10×) above that bin's learned baseline.
- A broadband noise-floor rise of at least +10 dB above its temporal baseline,
  with at least half of the monitored bins also rising by +10 dB.

These are configurable engineering starting values, not a calibrated signature
of an unidentified phenomenon. The existing 436 saved one-second snapshots had
peaks from +11.5 to +20.7 dB above their current floor. Replaying them produced
zero captures under the combined defaults; only 113 snapshots had sufficient
preceding fresh data for a learned baseline. This small observational check does
not establish a long-term false-alarm rate or sensitivity to all possible events.
Replay results are in `run/rf-trigger-replay-results.json`.

The UI exposes power ratios, baseline change, broadband rise, confirmation count,
capture duration, cooldown, baseline window/warm-up, minimum bandwidth, rearm
margin, quiet snapshots, and maximum start delay. Source gaps, invalid values,
and other receiver bands do not count as confirmations. Repeated reads of one
snapshot do not count twice. One persistent event remains latched until quiet,
and a default ten-minute cooldown prevents repeated captures.

RF capture takes priority over frame export. The exporter is suspended (including
its hashing I/O) while the new recording runs, then resumes. If a recording is
already active, an event marker is added and capture is extended to include three
minutes after detection, within the two-hour safety cap. Actual stimulus playback
has its own duration, so extending a CE5 video does not falsely report early audio
termination. RF-only captures defer scheduled sessions by the configured gap.

Evidence is saved as `rf-trigger-events.json`: confirmation snapshots, the actual
baseline, thresholds, frequencies, power differences, trigger and capture times,
and the selected action. Late events that could not begin within the configured
maximum delay are reported as missed rather than treated as timely captures.
A restart relearns the baseline; cable-swap helpers preserve the enabled state.

### External observation references

The [published S3E7 analyzer screenshot](https://www.rtl-sdr.com/wp-content/uploads/2022/06/rtlsdrv3_skinwalker_ranch.jpg)
is centered near 1.680 GHz, outside this receiver's current 1.590–1.610 GHz
window. Its differently zoomed displays are not a transferable power threshold.
[Official HISTORY clip metadata](https://www.youtube.com/watch?v=rc1jY9AiMQ8)
confirms the programme source, while an additional Sky HISTORY clip was region
restricted during inspection; no viewing or numerical measurements of that
restricted clip are claimed.
[Rohde & Schwarz's analyzer fundamentals](https://www.rohde-schwarz.com/au/products/test-and-measurement/essentials-test-equipment/spectrum-analyzers/understanding-basic-spectrum-analyzer-operation_256005.html)
explain that reducing resolution bandwidth tenfold can lower the displayed noise
floor by about 10 dB. Receiver gain, bandwidth, averaging, and binning must match
before instrument readings can be compared. A broadband rise may also reflect
receiver settings, overload, or local interference; this trigger records it
without assigning a cause.


### Motion-triggered recording

Motion capture has independent persistent controls at `/api/motion-trigger/configure`
and a Motion trigger panel in the dashboard. Defaults: 3-minute video + RF,
no cooldown, 0.5% minimum changed region, 25/255 pixel difference,
0.5-second confirmation, 0.5-second reference, 40% maximum changed region,
full-image region. Motion is enabled on this station. Hourly and RF settings
remain independent. A trigger extends an existing recording or pauses postprocessing
and starts a priority recording; it does not open another camera input. Capture
requires fresh RF and camera data and the mounted T7. Events delayed over 30 seconds
are marked missed. No pre-roll video is implied: before/after native JPEG evidence
is retained separately from the video which begins after confirmation.

Analysis reads the atomic RAM preview at 10 fps, with grayscale 640×360 comparison,
uniform exposure compensation and isolated-pixel filtering. This analysis rate
is independently tunable up to 60 fps; achieved rate is shown in the UI. It does
not change native 1080p60 recording or export of every recorded frame. Very small
or fast objects can escape these initial analysis thresholds. Trees, clouds,
insects and camera movement may trigger; restrict the region or tune thresholds
based on observed results. A region uses percentage coordinates and changed-area
percentage is relative to that region. Quiet time is required to rearm.

Evidence is in `motion-events.json` and `motion-<eventid>-before/after.jpg`, linked
in session review, with event markers and SHA-256 file entries. Local dependencies
are Debian python3-numpy, python3-pil, libimagequant0 and libraqm0 extracted into
`vendor/root`. The user-service `motion.conf` drop-in sets PYTHONPATH and
LD_LIBRARY_PATH to this vendor tree and its lapack directory. For command-line
tests use the same environment. `swap_t7.py` disables and restores the motion
trigger alongside the RF trigger and schedule during safe cable changes.

Current small/fast-motion profile (saved in run/motion-trigger.json): analysis
60 fps requested, 0.01% changed area, 15/255 pixel difference, 0.1-second
confirmation and reference, zero cooldown. This replaces the initial conservative
live profile after a reported missed bird. Achieved analysis FPS is shown in the
UI and can vary with load; analysis still uses the latest RAM preview rather
than a guaranteed every-frame feed. A synthetic 6×6 analysis-pixel moving target
is covered by the motion tests. The reported bird itself was not retained, so its
specific rejection cause cannot be reconstructed.

The current camera framing uses a sky-only motion region: left/top 0%, right
100%, bottom 68%. This excludes visible foreground trees; the dashed preview
outline shows the detection region. Video and exported JPEGs remain full frame.
Revisit the region coordinates in the UI when moving the camera.


### Startup and power-loss recovery

The dashboard is an enabled user service with login lingering, Restart=always,
and restart-rate limiting disabled. Automatic settings, RF thresholds, motion
region/sensitivity and zero cooldown are persisted with atomic replace and
file/directory fsync. Explicitly disabled features remain disabled after restart.
Schedules wait for missing SSD/RF/camera resources instead of switching themselves
off. Interrupted pairs resume with a fresh silent baseline, not a CE5 continuation.
RF re-learns its baseline after boot; motion warms up before rearming.

Interrupted native recordings retain their original video.mkv, are marked invalid
and interrupted, and are queued for playback/frame recovery. Recoverable complete
packets are exported without converting the trial into a completed experiment.
Queued/in-progress exports resume after restart or a late SSD mount, with periodic
queue reconciliation. An interrupted archive may lack the last buffered frames;
no software can recover bytes that never reached the SSD. Permanent corrupt
archives retain a failed export record; subsequent scheduled cycles can continue.

Run `sudo /home/hackrf/capture-station/install-recovery.sh` once to install the
root-owned storage/RF recovery helper and system timer. It retries the exact T7
UUID mount and failed RF/SMB services every minute, verifies UUID and volume
marker before starting disk writers, and retries a stalled RF source after three
minutes. It never formats or forcibly unmounts storage. The UI Automatic actions
panel reports whether this timer is enabled. Root installation requires local
sudo authentication; application recovery works independently of this helper.

Validation covers transient RF loss, missing/late SSD, interrupted manifests,
export queue reconciliation, exact-drive safeguards, saved schedule restoration,
and native full-frame export. A real power-cut/reboot is not part of deployment.
Camera recovery depends on the Canon having power and delivering HDMI; software
cannot turn a physically powered-off camera back on.

Current native-detail profile (supersedes small/fast profile above): 1920-pixel
analysis width, 30 analysis fps requested, 0.001% changed area, 15/255 pixel
difference, 0.5-second reference and 0.1-second confirmation. Native JPEG grayscale
detail is retained, and the local filter preserves thin features with three
neighboring changed pixels. Exposure is estimated from a spatial subsample for
performance. Sky region remains top 68%, with zero cooldown; native 1080p60 video
and every-frame exports are unchanged. Analysis width is independently tunable in
the UI. An observed plane in the saved diagnostic image is about 18×4 native pixels;
the old downscaling/filter/area combination could erase its motion. A synthetic
thin silhouette at native scale is now covered by a trigger test. No claim is
made that the originally missed pass was automatically recorded.

Motion recordings now have a fixed configured duration (currently 3 minutes).
Further motion during any active session adds evidence and markers without
extending its duration. Zero cooldown remains; a subsequent qualifying event can
start a separate session after the current recording stops and motion rearms.
This supersedes the earlier motion-extension behavior described above.

Motion evidence is now visible under the camera in the Motion events panel, for
both active and saved sessions. It shows timestamps, precise changed-area scores,
original/comparison JPEG links, and boxed trigger images. New events save a
separate native-resolution `motion-<id>-boxed.jpg` without altering the original
trigger JPEG. Connected-component boxes mark changed regions, including possible
old/new object positions, rather than classifying objects. Metadata coordinates
are in original-frame pixels. Existing events can be boxed using the UI button
(`/api/motion/annotate`); historical evidence is recomputed from its saved pair.
The list shows the newest 20 by default with a show-all toggle. Images load when
expanded. The configured motion duration is a fixed limit; new motion annotates
existing recordings without extending them. Deployment retained the long videos.

Storage measurement on 2026-10-26: 546 GiB used, 325 GiB available; 545 GiB in
sessions. Two extended sessions alone held 142.26 and 136.59 GiB of native video,
with their frame exports still queued. A verified 3-minute session occupied about
14 GiB including native video, every-frame JPEGs and playback MP4. No recordings
or exports were deleted as part of this correction.


### Event windows and RAM pre-roll (current motion policy)

Motion capture now supersedes the fixed-duration policy: it saves 10 seconds
before first confirmed motion, continues during confirmed motion, and closes
10 seconds after the last confirmed motion. Brief unconfirmed pixel flicker does
not reset the quiet timer. Pre-roll (0–30s) and post-roll (1–60s) are tunable in
the UI. There is no cooldown. Scheduled and RF sessions retain their configured
durations; an RF hit during a motion window preserves its required RF recording
period too. Motion continuing beyond a scheduled/RF session hands over to a
motion window with overlap. A two-hour safety limit remains for uninterrupted
motion; the 2 GiB storage reserve also remains.

The camera continuously copies native MJPEG packets to one-second Matroska
segments under `/dev/shm/field-station-<uid>`. Only a bounded pre-roll ring plus
segment-boundary margin is retained in RAM (normally 12–13 seconds, about
550–600 MiB on the current scene); hard RAM retention cap is 1.5 GiB. Idle footage
expires without SSD writes. Clip start/stop does not reopen the camera. On motion,
closed segments covering the desired window are copied to the T7, followed by
live segments through the post-roll deadline. RF snapshots are buffered in RAM
and written with the same clip-relative time base. A newly booted or retuned
camera can supply only the available pre-roll; the manifest reports incomplete
pre-roll and the UI shows the available seconds.

A dedicated assembler losslessly joins/trims saved segments into `video.mkv`
while respecting capture-priority pauses. This avoids waiting behind older,
long JPEG exports just to obtain the original clip. Scratch segments are removed
only after the archive is fsynced, hashed and committed. Original packets remain
in video.mkv; every-frame JPEG export and 60 fps MP4 creation continue through
the export queue. Space estimates prevent starting exports that cannot fit;
those jobs wait for storage without reducing FPS or deleting recordings.

`buffer-state.json` records source segments, requested UTC interval and trim
positions. Original packet timestamps are preserved within segments; host UTC
mapping is estimated from the first segment's write time, so HDMI latency and
small host-clock offsets remain uncalibrated. Recovery retains interrupted
spooled segments and assembles the available video after restart. RAM history
cannot survive loss of power, but already-spooled closed segments can recover.

Validation covers native segment rotation, exact packet hashes after boundary
trimming, full 60 fps frame export, pre-roll warm-up, quiet-timer resets, pending
exports and storage limits. Live camera validation also located the exact
trigger JPEG by SHA-256 around 10 seconds into a captured clip and verified RF
snapshots and the complete saved tail.

### Custom detection borders

The preview's Edit border button opens a polygon editor, including in fullscreen.
Tap/click the picture or border to insert a point on the nearest edge; drag the
handles with mouse, pen or touch. Remove point deletes the selected vertex while
keeping at least three. Reset rectangle restores the legacy rectangular bounds.
Save border activates and persists the polygon; Cancel leaves detection unchanged.
Coordinates are normalized image percentages, so fullscreen and resized previews
use the same border. The editor supports 3–32 points and rejects crossing edges,
repeated points and regions smaller than 0.1% of the image. Concave borders can
exclude individual foreground treetops.

The detector caches a raster mask for the selected polygon and scores only its
included pixels. Exposure compensation and connected-region evidence annotations
use the same mask; excluded pixels do not contribute to triggers or boxes. The
saved polygon is copied into every event's settings and survives service restart
and the safe SSD cable-swap workflow. Existing rectangles remain active until a
polygon is saved. Legacy rectangular API updates clear the custom polygon;
ordinary sensitivity and timing changes keep it.

### Remote M1 worker

The Pi remains responsible for camera/RF capture, session manifests, scheduling,
verification, uploads, and retention. When `private/m1/config.json` enables the
worker, playback preparation calls `m1_encode.py` using dedicated key-only SSH
with pinned host identity. The Mac receives an original MJPEG file, verifies its
SHA256, encodes H.264 with the existing ultrafast CRF18 policy, and returns a
faststart MP4. The Pi checks frame count, codec, dimensions and square pixels
before publishing it to the upload queue. Originals remain under the existing
verified-offsite retention policy. SSH failures leave originals available for
retry. Set `enabled` false in the protected config to return new jobs to Pi
encoding; configuration is checked per job.

`m1_worker.py` is deployed under `~/field-station-worker` on the Mac. Temporary
input and output live under `~/Library/Caches/field-station`, are removed when a
job exits, and require 20 GiB of disk reserve. Encoding is serialized on the Mac;
receiving a large job does not lock out smaller completed transfers. Keep the
Mac powered and awake. Existing SSH credentials are in protected `m1.creds`;
unattended jobs use their dedicated key instead of the password.

`youtube-live.service` is a separate Pi controller. It checks YouTube permission
every ten minutes. Once allowed, it prepares one unlisted ten-minute 720p30 test,
sends its ingestion settings privately to `m1_live.py` over SSH, and polls
YouTube's broadcast status. The Mac uses VideoToolbox H.264 and silent AAC audio,
then sends RTMPS directly to YouTube. The trial temporarily owns the encoding
lock so bulk encoding does not compete with it. The test completion is durable
and does not automatically become a continuous stream. Status and a watch link
appear in the dashboard. Stop it with `systemctl --user stop youtube-live`.
The current Tailscale-relayed camera link was measured at about 21 distinct
frames/second; the encoder fills a 30-fps output with repeats. A true 30-fps
source requires a faster camera transport. The camera JPEG endpoint reuses the
existing capture and does not open the Cam Link a second time.

### Aircraft capture repair (2026-10-27)

Recent triggered sessions contained JPEG evidence of aircraft but empty segment
lists. The camera started before initial NTP synchronization; the ring retained
its earlier UTC anchor. Segment ingestion now corrects UTC mapping when segment
completion times diverge by more than two seconds, including retained segments.
A regression test simulates a 600-second clock correction and verifies clip data.
The active full-image motion threshold is now 0.002% (about 42 changed pixels at
1080p), with pixel difference 18, cloud suppression enabled, and 0.1-second
confirmation. This improves small-object sensitivity but can increase false
triggers; aircraft classification is not performed.

The camera preview displays live yellow motion boxes through a browser SVG
overlay, polled from `/api/motion-overlay` five times per second. Coordinates
come from current motion analysis inside the configured border; cloud suppression
and scene-change rejection apply. Boxes expire when analysis is stale or disabled.
This display layer never modifies camera JPEG packets or recorded video. Changed
regions are not object classifications, and overlay positions can lag the preview
by an analysis/poll interval.

Night sensitivity was adjusted on 2026-10-27 after a 20-frame live sample showed
cloud-suppressed scores peaking at 0.00188%, below the previous 0.002% trigger.
Active settings: cloud suppression off, pixel difference 12, minimum area
0.0005% (roughly 11 full-resolution pixels), comparison interval 0.8 seconds,
confirmation 0.1 seconds. A copy of the prior settings is in
`run/motion-before-night-tuning.json`. These settings prioritize faint motion
and can trigger on sensor noise; they do not identify an object or cause.

The night sensitivity experiment was reverted after it triggered on noise.
Active filtering again uses cloud suppression, pixel difference 18, minimum
area 0.002%, and a 0.4-second reference. Confirmation is now 0.5 seconds.
Live boxes are displayed only after confirmation and only for regions meeting
the minimum area, rather than displaying every below-threshold candidate.

### Daytime and nighttime motion presets

The Motion filters selector provides manually applied Daytime and Nighttime
presets. The active preset persists across restarts; manual edits to filter
thresholds label the configuration Custom. Switching presets retains the saved
region, recording windows, enabled state, and analysis resolution/rate.

| Preset | Pixel difference | Minimum area | Confirmation | Reference interval |
| --- | --- | --- | --- | --- |
| Daytime | 18 | 0.002% | 0.5 s | 0.4 s |
| Nighttime | 12 | 0.0012% | 0.4 s | 0.8 s |

Both retain compact-region/cloud filtering, exposure compensation, and 2% scene
change rejection. Nighttime is an initial compromise between missed faint detail
and sensor noise, not a guarantee of detecting all visible motion. The camera's
native recording stream is unchanged. Automatic day/night switching is not enabled.

Nighttime mode additionally tracks tiny changed regions that the compact-area
filter excludes. It requires at least four consecutive nearby detections over
0.5 seconds, at least six pixels of displacement, consistent direction, bounded
prediction error, and a subsequent normal confirmation interval. Static or
back-and-forth flicker does not qualify. This path uses native grayscale detail
at the configured pixel threshold; daytime behavior is unchanged. Events identify
`night-small-trajectory-v1` and retain `small_motion_regions` coordinates.
Replay of the reported center-to-lower-left passage produced coherent detections
near (759,706) through (705,781); this is motion evidence, not classification.

Fullscreen preview chrome fades after five seconds without pointer activity.
Moving the pointer, tapping, or using the keyboard restores it. Controls, region
border, camera label, and standby badge fade; live tracking boxes and an active
recording badge stay visible. This applies to native fullscreen and the iPad
viewport fallback, and does not alter recording or motion analysis.

### Click-to-track

Click or tap a target directly in the live camera image to select it, including
in fullscreen. Region editing keeps its existing drag/add behavior. The server
seeds a 16×16 native grayscale template at the clicked point, searches nearby
positions on subsequent analysis frames, and requires normalized correlation
of at least 0.65. A mint box marks the selected target; a weak match shows TARGET
LOST and is abandoned after two seconds. A flat selection is rejected with a
message asking for distinct detail. Stop tracking releases the selection.

Selecting a target immediately requests a buffered motion capture or annotates
an existing recording, independently of automatic motion being enabled. Matching
frames keep the motion post-roll window alive. Events record the normalized
selected point and `user-selected-template-v1`; this is observer selection, not
automatic confirmation or object identification. The selected-target overlay
stays visible when fullscreen controls fade and is never burned into video.

YouTube Live permission checks are manual-only as of 2026-10-28. The user service
is disabled and stopped. A manually started test exits after a permission or
encoder error without scheduling another attempt.

### Shape and object labels (2026-10-28)

New motion events receive background, label-only analysis. The Pi measures a
single-frame silhouette (round, elongated, irregular, too small, or unresolved);
it does not measure the before/after difference as object shape. It reports
native pixel dimensions, circularity, axis ratio, fill, and contrast threshold.
JPEG ringing is excluded using a contrast-dependent threshold. Appearance labels
are separate from object identification.

The Mac `vision_worker` helper runs Apple's Core ML YOLOv3 FP16 COCO detector on
small JPEG crops from the two comparison frames. Labels are bird, airplane,
other animal, or unknown. A label requires two model scores >=0.8 with at least
16 native pixels of target detail, or a single score >=0.97 with >=32 native
pixels, explicitly marked as a single-frame suggestion. These are engineering
thresholds, not calibrated probabilities. Weak, unavailable, or tiny detections
stay unknown. All events continue recording; classification never suppresses a
trigger or deletes footage. The helper accepts a bounded JSON batch over the
existing SSH connection and retains no input images. Model download source:
https://developer.apple.com/machine-learning/models/ (YOLOv3FP16.mlmodel).

Motion events show shape and suggested object labels, with an Analyze/Recheck
button while original comparison frames remain local. Historical events with
available originals are classified in the background; new events have priority.
An offline Mac leaves shape results available and object labels unknown.

The independent boxed-frame collection is also organized into:

- `T7/sessions/boxed-frames/classified/objects/{bird,airplane,other_animal,unknown}`
- `T7/sessions/boxed-frames/classified/shapes/{round,elongated,irregular,too_small,unresolved,unreviewed}`

A multi-target frame can appear in several folders. The flat boxed collection
and originals remain available. Copies are independent, existing labels survive
source cleanup, and reclassification replaces only obsolete categorized copies.
`classification-index.json` records each boxed filename's folder labels.

Validation: `python3 -m unittest test_object_analysis test_boxed_frames test_motion_trigger -q`
with the service's vendor PYTHONPATH/LD_LIBRARY_PATH. Real-frame validation is
saved in `run/classification-validation.json`. Apple Vision's generic whole-image
classifier was rejected after it missed a clear saved bird; the dedicated YOLO
object detector is used instead.

Live motion boxes now include text labels; recent classifications are attached
only when spatially overlapping and under five seconds old, otherwise the box
shows `Motion | analyzing`. Saved boxed frames are regenerated from their clean
original comparison frames after analysis, displaying suggested object and shape
labels. Originals and recorded video remain clean. Classified image checksums
and event metadata are updated together; the browser cache key includes the
classification timestamp. Label rendering and classification-folder assignment
were verified with an actual saved bird frame; the sampled small aircraft
remained unknown and was not filtered out.

### Web review and custom-model training data

Open **Review boxed frames** from Motion events or visit `/boxed-review`. The
page lists the entire independent boxed-frame collection with pagination,
search by filename/event ID, object filters, and reviewed/unreviewed filters.
It supports iPad touch selection, a magnified target view, object and shape
corrections, drawing/replacing/removing boxes, no-object negatives, notes, and
Save & Next.

Observer corrections are stored separately as `human_review` in the event and
manifest. They override display and classification-folder placement while
retaining the original model output. Rechecks cannot replace an observer's
review. Reviewed boxed images are regenerated from the clean original frame.
The original images and source video remain unchanged.

Durable reviews, clean source snapshots, and review history are retained under
`T7/training/`. Save a label correction immediately, then check **I checked all
target boxes and labels for training** when the frame is fully annotated. A
training-ready frame must have confirmed boxes and no unknown target labels;
a confirmed empty frame is a negative example. Boxed-only frames can still be
reviewed, but are excluded from training when a clean original is unavailable.
Reviews with unconfirmed boxes
are retained but excluded from training exports.

**Download training examples** produces a ZIP containing clean native images,
normalized YOLO-format bounding boxes, class names, and session/event metadata.
Training and validation splits must be separated by recording session, rather
than randomly mixing neighboring frames from one passage. For tiny targets,
prepare native-resolution tiles/crops or use adequate training resolution;
shrinking the full 1080p image to a small input can erase the relevant detail.
Changing a review does not automatically retrain the running model. Fine-tuning,
held-out evaluation, and replacement of the deployed model remain separate
steps after enough varied reviewed examples have been collected.

The review UX now opens one frame directly on the page, defaulting to unreviewed
captures. Skip advances without changing labels or review state. Save & Next
persists the correction and opens the next matching frame automatically. Skipped
frames are excluded only for the current pass and can be revisited with Review
skipped frames. Search, filters, and export remain under a collapsed options
panel. The thumbnail wall, pagination controls, and drill-in modal are removed.

Cloud is a review/background label. Selecting it hides the region box in the
review canvas and magnified view. Saving preserves the observer correction but
renders no box around that cloud in the boxed image; recent matching cloud
labels also suppress the live preview box. Cloud-reviewed frames are organized
under `classified/objects/cloud`. Confirmed clean cloud examples remain eligible
for training exports, with cloud regions omitted from detector bounding-box
labels (negative/background examples). Other objects in the frame retain their
labels and boxes. Existing heuristic cloud suppression still applies to live
analysis; reviewed examples do not automatically retrain the deployed model.

Anomalous is an observer review flag for follow-up. It retains the target box
and shape, and sorts into `classified/objects/anomalous`. It is deliberately
excluded from ordinary object-identity training exports; the original model
prediction remains available alongside the observer flag.

Review frames now include **Verify with source video** and a jump near the
approximate capture time. Local full MP4s are preferred, followed by verified
Internet Archive copies. When the original MKV is local but the archival MP4
is pending, Play source video queues a short 960×540 / 15 fps H.264 event preview
on the Pi. This one-at-a-time, low-priority worker produces up to twelve seconds
around the event without transferring the full recording to the Mac. It does
not replace or alter the original or archival video. Timestamps are approximate;
the earlier comparison frame subtracts the configured reference interval.
Seeking uses normal byte-range support. Changing review frames clears playback
and ignores any old frame's late preparation response.

Motion boxes also save a clean native-pixel crop as lossless PNG plus a JPEG
close-up enlarged to at least 1024 pixels on its long edge. The enlargement uses
Lanczos resampling and mild display smoothing; it adds no generated detail.
New annotations generate these automatically; older review frames generate them
on demand. The review panel shows the saved smoothed close-up, its native crop
dimensions, and a link to the native PNG. Unsaved box edits use a smoothed live
canvas preview. Training exports continue using clean original images rather
than smoothed or boxed derivatives.

### Camera-model training and deployment

`station-model-training.service` is a separate Pi controller, so a capture-service
restart does not interrupt training. The review page shows the active model
version, progress, held-out results, Train now, and an automatic-training toggle.
Automatic batches require ten new/changed confirmed examples and at least thirty
minutes between attempts. Notes and timestamps do not count as changed training
supervision. No model is trained on unconfirmed, unknown, or anomalous labels.

Each run snapshots clean native target crops matching the inference crop policy.
Eligible categories need six independent recording sessions. Session assignments
are persistent: training, calibration, and test each retain at least two sessions
per trained class. A recording never crosses splits or moves from held-out data
into later training. The first run used 31 training crops, 20 calibration crops,
and 14 test crops from 25/10/9 distinct recording sessions respectively.

The Mac uses ImageNet MobileNetV3 Small features and fits a camera-specific linear
classifier with augmented training crops. Core ML export is checked against the
PyTorch probabilities, then evaluated through the actual Swift/Vision inference
path. Calibration requires correct high-confidence predictions from two separate
sessions with no calibration false positives. Held-out deployment requires at
least 90% known-object precision, improved mean bird/airplane F1, no decline in
either class's recall, and no false cloud suppression. The previous active model
is evaluated on the same held-out samples. Failed candidates never replace it.
The immutable exported package, dataset snapshot, logs, and evaluation remain in
`T7/training/runs/`; the Mac retains corresponding trained artifacts.

Activation changes the Mac's `active-model.json` atomically and verifies an actual
held-out prediction. Failure restores the previous pointer. The original YOLO
model remains a fallback when a camera-specific prediction abstains. Supported
camera-model suggestions can identify targets down to eight native pixels;
the legacy 16-pixel gate remains for uncalibrated baseline detections. After
activation, unreviewed events are reclassified automatically; human labels and
anomalous flags are never overwritten. Classification remains label-only: every
capture is retained. Small pilot test results are displayed explicitly and are
not a claim of a general false-positive rate.

### Dedicated anomalous event collection

Observer-flagged events are independently copied to
`T7/sessions/anomalous/<session-id>--<event-id>/`. Packages contain the boxed image,
original comparison frames, available close-ups, and `event.json` with the review
and source-video reference. Existing sessions and videos remain in their original
locations. The boxed-frame service refreshes these packages as evidence becomes
available, and saving an anomalous review updates the collection immediately.
