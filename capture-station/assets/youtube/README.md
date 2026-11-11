# YouTube artwork

Approved 11 November 2026. The channel banner is 2560 × 1440 with the logo centered vertically and the lockup inside the mobile-safe area. Scheduled broadcasts use the full-frame thumbnail.

The photographed detection is starred review `3ac48ccca0b515f0a570191cde0606fa`, the fifth from the end of the starred list when selected. Its original color thumbnail was cropped and uniformly scaled, then reduced by 25% inside the box. The detection itself was not generated, reshaped, or recolored. The surrounding branded sky is AI-edited artwork, not original observation footage.

`youtube_sessions.py` applies the configured `thumbnail.video_still` and `thumbnail.revision` to the current and next sessions. Receipts are saved per session; failed updates retry after five minutes without blocking stream handoffs. Upload-resource settings remain in the field runtime configuration. `thumbnail-status.json` reports success or pending retries. The camera-loss standby screen and live watermark are separate assets.
