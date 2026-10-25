# M 0.21.0 — Brand and experience refinement

## Product identity
- The visible product name is now **M**.
- The brand line beneath the M wordmark is **Manage. Connect. Grow.**
- The longer product category remains in descriptive documentation and metadata rather than appearing as the product name in the interface.
- The app title, footer, PWA manifest, and SVG lockup now follow the same identity.

## Experience and accessibility
- Refined the sign-in/setup card, responsive spacing, form control sizing, contrast, and visual hierarchy.
- Preserved keyboard-visible focus indicators and reduced-motion preferences.
- Bumped frontend asset references and the service-worker cache key to move installed clients away from stale 0.20.0 shell assets.

## Engineering and compatibility
- No intentional schema, credential, permission, or API contract changes were made in this identity-focused release.
- Kept historic internal paths and the `midar_token` session key to reduce compatibility risk.
- Added CI checks for Python tests, JavaScript syntax, and regenerated stylesheet consistency.

## Integration status
- This release does not claim that every social platform is fully connected or authorized.
- The current connector catalogue remains the source of truth for supported capabilities; Telegram support remains limited to the documented actions.
- Google sign-in is for M identity, not automatic authorization for social publishing.
