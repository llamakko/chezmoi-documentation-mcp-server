# Security Policy

## Supported Versions

Until `1.0.0` is released, security fixes are applied on a best-effort basis to:

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Latest tagged release | Yes |
| Older releases | No |

## Reporting a Vulnerability

Please do not report security vulnerabilities in public issues or pull requests.

Preferred reporting channel:

1. Use GitHub's private vulnerability reporting for this repository if it is enabled.
2. If private reporting is not enabled, contact the maintainer through a private channel before disclosing details publicly.

Please include:

- A clear description of the issue
- Impact and affected components
- Reproduction steps or a proof of concept
- Any suggested remediation if you have one

If you are unsure whether something is security-sensitive, report it privately first.

## Scope

Security reports are especially helpful for issues involving:

- GitHub Actions or release workflow abuse
- Supply-chain risks in build, release, or dependency handling
- SSRF, redirect validation, or external fetch bypasses
- Output injection or unsafe handling of untrusted documentation content
- Credential leakage, secret exposure, or token misuse
- Privilege escalation in MCP tool behavior

## Disclosure Expectations

- Please allow time for investigation and remediation before public disclosure.
- After a fix is available, coordinated disclosure is welcome.
- Reports that include enough detail to reproduce and assess impact will be triaged faster.

## Hardening Notes

This repository aims to keep the following defaults in place:

- Pinned GitHub Actions revisions
- Least-privilege workflow permissions
- Protected release workflow gating
- Official-host restrictions for documentation fetching
- Input validation, output sanitization, and response size limits
