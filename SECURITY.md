# Security Policy

Harry is a small experimental tool designed for home lab environments.

It is **not intended for direct exposure to the public internet**.

## Supported Versions

At present, no formal version support policy exists.

The project is experimental and evolving.

## Reporting a Vulnerability

If you discover a security issue, please report it privately rather than opening a public issue.

Please use a private GitHub security advisory or the repository maintainer contact listed on the hosting platform.

Please include:

- description of the issue
- reproduction steps
- affected component

## Deployment Guidance

If running Harry outside a trusted network:

- place it behind an HTTPS reverse proxy
- restrict access via firewall
- do not expose `/ingest` publicly without authentication
