# Field storage retention

Human review controls durable storage. Model predictions alone do not authorize public uploads.

- Human-reviewed anomalous evidence is uploaded to Internet Archive with its full original video, annotations, and original/annotated frame pairs. Local evidence can be removed only after the current review bundle passes remote checksum and download verification.
- Every human-reviewed object retains its independently verified training crop and label. Local duplicate images, review clips, and source recordings are removed when no pending detection or unverified anomalous review needs them.
- Clear backlog discards unreviewed detections and deletes their media. It establishes a cutoff so a new model can be tested against fresh detections, without erasing human-reviewed training examples.
- Small labels, provenance, deletion journals, and upload receipts remain so training and cleanup are auditable.
- Shared source segments remain until their last pending use is released. Active capture and recognition acknowledgments guard completed-recording cleanup.

The archive-export loop runs reviewed-media retention after export reconciliation. Each pass limits event and recording cleanup work. It checks current human reviews under the review lock, verifies the independent training crop, and binds anomalous cleanup to the exact uploaded annotation revision. Changed reviews and failed verification retain evidence.

Status: `retention/review-media-status.json` on the capture volume. Deletion journal: `retention/review-media.jsonl`. Each retired event has a small `local-media-retired.json` record to prevent source media from being recreated. The spool collector continues to require analysis acknowledgments.

The existing capacity offloader remains an overflow mechanism for unresolved recordings. Its private archive is not proof of Internet Archive publication. All capture, training, and archive data remains on external storage.
