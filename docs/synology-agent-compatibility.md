# Synology Agent Compatibility

Harry currently supports two Linux agent installation paths:

- `linux-systemd`: the standard Linux install that uses a systemd service and timer.
- `synology-dsm`: a DSM-friendly install that avoids systemd and runs the agent from a persistent NAS path.

## Supported today

- Shell-based agent install and updates.
- Agent runtime checks over HTTP.
- DSM-friendly wrapper execution from Synology Task Scheduler.
- Baseline telemetry from common Linux tools plus DSM version detection when available.

## Assumptions that still need to hold

- `bash` must be available for the Harry agent script itself.
- `curl` and `python3` must be available for the installer and agent runtime.
- The agent must be able to reach the Brain over HTTP.
- The install target must be writable and persistent.

## Unsupported for this pass

- Synology SPK packaging.
- Synology API integration.
- systemd on DSM.
- SMART or drive-health remediation.
- Full remediation workflows.

This keeps the first DSM pass intentionally small: install the Harry Agent safely, run it from Task Scheduler, and report reliably.
