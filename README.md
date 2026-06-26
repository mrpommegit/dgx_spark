# DGX Spark Operations Notes

This folder is used to maintain DGX Spark best practices, configuration notes,
fine-tuning guidance, and proposed stack decisions.

## Scope

- Best practices for running and maintaining DGX Spark systems.
- Configuration scripts and repeatable setup procedures.
- Fine-tuning notes, experiments, and operational recommendations.
- Stack proposals for security, networking, tooling, observability, and model
  workflows.

## Current Contents

- `security/dgx_spark_network_mode.py` - Ubuntu tray indicator for switching
  DGX Spark network/privacy modes using `nftables`.
- `Wifi_alwaysON.sh` - NetworkManager helper to keep a configured Wi-Fi
  connection enabled and reconnecting.
- `security/` - Security-related scripts and configuration proposals.
- `finetuning/` - Fine-tuning support scripts, notes, and workflow proposals.

## Suggested Structure

Use these folders to keep future work easy to review:

- `security/` - Firewalling, privacy modes, access controls, hardening, and
  threat-model notes.
- `finetuning/` - Fine-tuning recipes, dataset preparation notes, training
  configuration, evaluation plans, and experiment results.
- `configs/` - Reusable system, service, network, and tool configuration files.
- `proposals/` - Stack proposals, design decisions, tradeoffs, and rollout
  plans.
- `docs/` - General DGX Spark operating procedures and best-practice notes.

## Contribution Notes

- Prefer scripts that are idempotent and safe to rerun.
- Document prerequisites, target OS/version, required privileges, and rollback
  steps for any system-level change.
- Keep machine-specific values, credentials, and secrets out of committed files.
- Add a short note beside each proposal explaining the problem, recommendation,
  tradeoffs, and validation plan.
- For fine-tuning work, record model name, dataset source, hardware assumptions,
  hyperparameters, evaluation method, and observed results.

## Safety

Some scripts in this folder can change network or security behavior. Review them
before running, and test changes in a controlled environment before applying them
to a production DGX Spark system.
