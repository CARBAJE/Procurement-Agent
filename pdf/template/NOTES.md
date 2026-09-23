# Eisvogel — Customisation Notes

This project uses [Eisvogel](https://github.com/Wandmalfarbe/pandoc-latex-template)
as its Pandoc LaTeX template without modification. All personalisation is done
through `metadata.yaml` variables.

---

## Variables Used

| Variable | Value | Effect |
|---|---|---|
| `titlepage` | `true` | Enables the Eisvogel cover page |
| `titlepage-color` | `1A3A5C` | Cover background (navy blue) |
| `titlepage-text-color` | `F5F5F5` | Cover text (off-white) |
| `titlepage-rule-color` | `F07C00` | Accent rule (orange) |
| `titlepage-rule-height` | `6` | Rule thickness in pt |
| `toc-own-page` | `true` | TOC starts on its own page |
| `listings` | `true` | Use `listings` package for code |
| `code-block-font-size` | `\small` | Slightly reduced code font |
| `table-use-row-colors` | `false` | Plain table rows |
| `disable-header-and-footer` | `false` | Show running header/footer |

---

## Adding a Logo to the Cover Page

1. Place a PNG or PDF file in `pdf/assets/` — ideally `logo.png` (500 x 500 px
   or larger, transparent background).
2. Uncomment the `titlepage-logo` line in `metadata.yaml`:
   ```yaml
   titlepage-logo: "assets/logo.png"
   ```
3. Rebuild.

---

## Changing the Colour Scheme

Edit the three `titlepage-*` colour variables in `metadata.yaml`. Values are
6-digit hex codes **without** the leading `#`.

Suggested palettes:

| Style | Background | Accent | Text |
|---|---|---|---|
| Infosys Navy/Orange (current) | `1A3A5C` | `F07C00` | `F5F5F5` |
| Dark Slate | `2D3748` | `68D391` | `FFFFFF` |
| Red Hat Red | `CC0000` | `F0AB00` | `FFFFFF` |
| AWS Orange | `232F3E` | `FF9900` | `FFFFFF` |
| GitHub Dark | `0D1117` | `58A6FF` | `E6EDF3` |

---

## Changing the Body Font

The fonts in `metadata.yaml` (`mainfont`, `sansfont`, `monofont`) require
XeLaTeX or LuaLaTeX. To list fonts available on your system:

```bash
# Linux / macOS
fc-list | sort

# Windows (in PowerShell)
[System.Drawing.Text.InstalledFontCollection]::new().Families | Select-Object Name
```

If a font is missing, comment out the three font lines in `metadata.yaml` to
fall back to Computer Modern (LaTeX default).

---

## Using a Custom Template

If Eisvogel does not cover a requirement:

1. Obtain the template source:
   `eisvogel.latex` from the Eisvogel releases page.
2. Copy it to `pdf/template/custom.latex`.
3. Edit as needed.
4. In `defaults.yaml`, change:
   ```yaml
   template: eisvogel
   ```
   to:
   ```yaml
   template: template/custom.latex
   ```

This keeps the stock Eisvogel intact and applies your modifications to a local copy.

---

## Eisvogel Version Compatibility

Tested with Eisvogel 2.x. The `titlepage-*` variable names changed between 1.x
and 2.x. If the title page looks incorrect, run `pandoc --version` and compare
against the Eisvogel changelog.
