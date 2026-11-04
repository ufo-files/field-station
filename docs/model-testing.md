# Saved-model tests

`/test-model` lists saved model packages with a Test action per row. The old `/?view=test` URL redirects here. Each request runs native Core ML crop inference against the same 500 images copied from the most recent existing random-training benchmark when this feature is initialized. The sample is pinned by checksum and shared across model rows and repeated tests; it is not resampled per click.

The test applies the saved anomaly threshold and minimum-size rule. Older multiclass packages are evaluated through the current binary decision: anomaly score at threshold is Anomalous, otherwise Not Anomalous. Runtime failures fail the test rather than being counted as negative predictions. Testing never calibrates thresholds, trains, promotes, or activates a model.

The main Mac's `app.ufo-files.model-tests` LaunchAgent runs every 15 seconds. Its worker uses the existing training configuration for SSH and external storage, serializes tests, and keeps its own compilation cache. Requests/results live under the field lab's `model-tests/`; pinned images, detailed predictions, and compiled packages live under the main training root's `model-tests/`. Pending requests survive service restarts. The UI shows results only for its current sample and distinguishes failures from untested models.

Accuracy is training-sample fit, not unseen-footage accuracy. The table also reports correct / total, anomalous precision and recall, and last-tested time. Blank scores are shown as — rather than being invented from training history.
