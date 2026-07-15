# Security policy

## Supported versions

Security fixes are applied to the latest marketplace release. Because the plugin
pins its MCP runtime, users should upgrade the whole plugin rather than replacing
one stack component in place.

## Reporting a vulnerability

Do not disclose vulnerabilities in a public issue, discussion, or pull request.
Use GitHub's private vulnerability reporting form:

<https://github.com/airmang/hwpx-plugins/security/advisories/new>

Include the plugin version, host, launcher mode, workspace layout, a minimal
reproducer, and impact. We aim to acknowledge a report within 3 business days
and provide a status update within 10 business days.

If the private form is unavailable, open a public issue containing no sensitive
details and ask the maintainer for a private reporting channel.

## Supply-chain controls

GitHub Actions are pinned to full commit SHAs, Dependabot monitors action updates,
pull requests receive dependency review, and CodeQL scans the Python launchers and
automation scripts. CI publishes a CycloneDX JSON SBOM for the tested runtime
environment. Generated host bundles must match their canonical templates.
