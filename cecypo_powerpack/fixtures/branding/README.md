# Public document link branding

Paste these into **PowerPack Settings → Banner & Footer**:

| File | Field |
| --- | --- |
| `public_link_header.html` | Header Content |
| `public_link_footer.html` | Footer Content |

Then clear **Builder Page Route** so the built-in viewer is used. It renders
these two fields, and it is the viewer that carries the Pay with M-Pesa
buttons.

The header sits on a white bar, so it is dark text on light. The footer paints
its own navy card, which keeps it readable regardless of the page background
and echoes the dark band on cecypo.tech.

Also tick **Hide Header** — the brand already appears in Header Content, and
leaving it off shows the company name a second time above it.

The header uses `var(--pp-text)` / `var(--pp-accent)` rather than fixed colours
so it follows the page's light and dark themes. The footer paints its own navy
card, which reads correctly either way.
