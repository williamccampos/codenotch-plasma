# Provider marks

PNG/SVG files for Claude, Grok and Antigravity come from the npm package
`@lobehub/icons-static-svg` 1.95.0 (https://github.com/lobehub/lobe-icons, MIT License),
matching the marks shipped in [vinzdg/codenotch](https://github.com/vinzdg/codenotch).

| File | Upstream | Provider |
|------|----------|----------|
| claude.svg | icons/claude.svg | Claude |
| grok.svg | icons/grok.svg | Grok |
| antigravity.svg | icons/antigravity.svg | Antigravity |
| openai.svg | icons/openai.svg | OpenAI / Codex |

`scripts/render-glyphs.py` builds `{provider}-dark.png` (white glyph) and
`{provider}-light.png` (black glyph) with transparent backgrounds.

Cursor and Kiro source PNGs are official product marks supplied by the maintainer.

**Trademarks**: these marks identify the products whose usage is displayed. They can be
replaced with generated glyphs without touching code.
