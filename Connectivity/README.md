# Connectivity Helpers

This directory contains remote-access and connectivity automation for DGX Spark
systems.

## Tailscale

`install_tailscale.sh` installs Tailscale, enables `tailscaled` when systemd is
available, and runs `tailscale up` with options loaded from the repository
`.env` file.

Basic setup:

```bash
cp ../.env.example ../.env
./install_tailscale.sh
```

For unattended setup, create a Tailscale auth key in the admin console and set
`TAILSCALE_AUTH_KEY` in `.env`. Leave it empty to use the interactive browser
login flow.

Useful `.env` options:

- `TAILSCALE_HOSTNAME` - device name registered in the tailnet.
- `TAILSCALE_ACCEPT_ROUTES` - set to `true` to accept advertised subnet routes.
- `TAILSCALE_SSH` - set to `true` to enable Tailscale SSH.
- `TAILSCALE_ADVERTISE_EXIT_NODE` - set to `true` to advertise this DGX Spark as
  an exit node.
- `TAILSCALE_ADVERTISE_ROUTES` - comma-separated subnet routes to advertise.
- `TAILSCALE_ADVERTISE_TAGS` - comma-separated ACL tags for tagged devices.
- `TAILSCALE_EXTRA_ARGS` - extra arguments passed directly to `tailscale up`.
