# Security Policy

Security reports should be submitted privately through GitHub's security-advisory interface for
`zephytiju/meridian-plugin-config-artifact`. Do not disclose a suspected vulnerability in a public
issue before coordinated remediation.

Version 1.x receives security fixes. Artifact payloads never enter Core JSON envelopes, public
errors contain only safe causes, and this package never accepts provider credentials or physical
storage locators. Applications remain responsible for identity, ACL, encryption, retention, and
binding configuration through Platform IaC.
