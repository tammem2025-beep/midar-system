# M — Brand identity 0.21.0

## Brand
- **Product name:** M
- **Tagline:** Manage. Connect. Grow.
- **Positioning descriptor:** Digital business management (used as a descriptive category, not the visible product name).
- **Personality:** calm, precise, trustworthy, connected, efficient.
- **Visual motif:** a clear monogram with a cyan → blue → violet gradient, balanced by deep-navy surfaces and high-contrast light surfaces.

## Application of the wordmark
- Show **M** as the product name.
- Place **Manage. Connect. Grow.** directly below the M wordmark wherever the full wordmark is used.
- Do not replace the wordmark with a platform logo or imply that a social provider is connected when it is not.
- The SVG wordmark in `frontend/brand-lockup.svg` is a centered stacked lockup. `frontend/brand-m-mark.svg` remains the compact monogram for small UI areas.
- Theme preferences may change the interface accents; the logo gradient stays stable.

## Color system
- Deep navy: `#0B1020`
- Cyan: `#06C6DE`
- Blue: `#5366FF`
- Violet: `#8B3FF2`
- Light page: `#F6F8FC`
- Light surface: `#FFFFFF`

Brand colors are decorative. Success, warning, and error states retain distinct semantic colors and labels.

## Accessibility and responsive rules
- Keep visible keyboard focus indicators.
- Respect `prefers-reduced-motion`.
- Keep the sign-in form usable on small screens, with controls at least 44px high where layout permits.
- Preserve the right-to-left Arabic application direction and readable text hierarchy.
- Do not rely on color alone to communicate status.

## Technical maintenance
- `frontend/styles-src/14-m-brand-identity.css` is the final source layer.
- Do not edit `frontend/midar-ui.css` manually; it is built with `python tools/build_frontend_css.py`.
- The service-worker cache name and versioned URL references must change with the shell release.
- Historical `midar` identifiers are internal compatibility keys and should only be renamed in a separately tested migration.

## Explicit capability boundaries
- Showing a platform in the catalogue is not proof of live authentication or publish permission.
- Google OIDC authenticates the M user only.
- Social OAuth, webhooks, scheduled publishing workers, provider review, and required platform approvals must be implemented and verified per provider before they are advertised as available.
