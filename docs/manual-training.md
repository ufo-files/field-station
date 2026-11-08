# Manual training

Training is started through **Train now**. The live controller configuration sets `automatic_training_enabled` to `false` and `provisional.enabled` to `false`. The controller still polls for manual requests every minute; that poll is not a training schedule. Pending publication and interrupted-deployment recovery remain enabled. Historical scheduled runs remain available in Training history.

The automatic scheduler checks the explicit disable flag before evaluating an hourly slot or falling back to review-driven training. Manual requests bypass that scheduler and retain their existing release behavior.
