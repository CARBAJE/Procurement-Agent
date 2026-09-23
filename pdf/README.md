# PDF Publishing System

Generates a single professional PDF from the 18 Markdown documents in
`project_docs/documentation/` using **Pandoc** and the **Eisvogel** LaTeX template.

---

## Quick Start

```bash
# Linux / macOS
cd pdf/
chmod +x build.sh
./build.sh

# Windows (PowerShell)
cd pdf\
.\build.ps1
```

The PDF is written to `pdf/output/procurement-agent-docs.pdf`.

---

## Prerequisites

### 1. Pandoc (>= 2.8)

| Platform | Command |
|---|---|
| Ubuntu / Debian | `sudo apt install pandoc` |
| macOS | `brew install pandoc` |
| Windows | `winget install JohnMacFarlane.Pandoc` |

Verify: `pandoc --version`

### 2. LaTeX Engine

A full TeX Live (Linux/macOS) or MikTeX (Windows) installation is recommended.
XeLaTeX is preferred (enables custom fonts). pdflatex and lualatex also work.

| Platform | Recommended package |
|---|---|
| Ubuntu / Debian | `sudo apt install texlive-xetex texlive-fonts-extra texlive-latex-extra texlive-fonts-recommended` |
| macOS | `brew install --cask mactex` or `brew install basictex` |
| Windows | [miktex.org/download](https://miktex.org/download) |

Verify: `xelatex --version`

> **Minimal TeX Live (Linux):** If you install only `basictex` or
> `texlive-xetex`, the build may fail with missing package errors on first run.
> MikTeX and the full TeX Live distribution install packages on demand.

### 3. Eisvogel Template

Eisvogel is not bundled with Pandoc — it must be installed separately.

```bash
# Linux / macOS
TMPL="$HOME/.local/share/pandoc/templates"
mkdir -p "$TMPL"
curl -sL https://github.com/Wandmalfarbe/pandoc-latex-template/releases/latest/download/Eisvogel.tar.gz \
  | tar xz -C "$TMPL"
```

```powershell
# Windows PowerShell
$tmpl = "$env:APPDATA\pandoc\templates"
New-Item -ItemType Directory -Force $tmpl | Out-Null
Invoke-WebRequest https://github.com/Wandmalfarbe/pandoc-latex-template/releases/latest/download/Eisvogel.tar.gz `
  -OutFile eisvogel.tar.gz
tar -xzf eisvogel.tar.gz
Move-Item eisvogel.latex $tmpl\
Remove-Item eisvogel.tar.gz
```

Verify: `pandoc --template eisvogel --print-default-template > /dev/null && echo OK`

### 4. Mermaid CLI (optional, recommended)

Without `mmdc`, Mermaid code blocks are rendered as plain code blocks in the PDF.
With `mmdc`, each diagram is pre-converted to an SVG image before Pandoc runs.

The documentation contains **31 Mermaid diagrams** across 13 files — installing
`mmdc` significantly improves the visual quality of the output.

```bash
npm install -g @mermaid-js/mermaid-cli

# Chromium/Puppeteer dependency (Linux headless):
mmdc --help   # triggers first-run browser download
```

Verify: `mmdc --version`

---

## Build Options

### `build.sh` (Linux / macOS)

```
./build.sh                  Default build with Mermaid pre-processing
./build.sh --no-mermaid     Skip Mermaid (faster, diagrams as code blocks)
./build.sh --open           Open PDF after successful build
./build.sh --help           Show usage
```

### `build.ps1` (Windows PowerShell)

```powershell
.\build.ps1                          # Default build
.\build.ps1 -NoMermaid               # Skip Mermaid
.\build.ps1 -Open                    # Open PDF after build
.\build.ps1 -LatexEngine pdflatex    # Force specific LaTeX engine
.\build.ps1 -NoMermaid -Open         # Combine flags
```

---

## File Structure

```
pdf/
  book.md          Chapter manifest — defines assembly order
  metadata.yaml    Document metadata and LaTeX / Eisvogel variables
  defaults.yaml    Pandoc CLI options (engine, template, flags)
  build.sh         Build script for Linux and macOS
  build.ps1        Build script for Windows PowerShell
  README.md        This file
  template/
    NOTES.md       Eisvogel customisation guide (colours, fonts, logo)
  assets/
    README.txt     Where to place logo and background images
  output/
    *.pdf          Generated PDFs (git-ignored)
```

---

## Customising the Output

### Chapter order

Edit `book.md`. Each non-comment line is a file path relative to `pdf/`.
Re-run the build script after saving.

### Cover page, colours, fonts

Edit `metadata.yaml`. Key variables:

| Variable | Default | Effect |
|---|---|---|
| `title` / `subtitle` | set | Title page text |
| `titlepage-color` | `1A3A5C` | Cover background colour |
| `titlepage-rule-color` | `F07C00` | Accent rule colour |
| `mainfont` | TeX Gyre Termes | Body text font (XeLaTeX) |
| `fontsize` | `11pt` | Base font size |
| `geometry` | 2.8 cm margins | Page margins |
| `toc-depth` | `3` | Heading depth in TOC |

See `template/NOTES.md` for a full customisation guide.

### Adding a logo

1. Place `logo.png` in `pdf/assets/`.
2. Uncomment `titlepage-logo: "assets/logo.png"` in `metadata.yaml`.
3. Rebuild.

### LaTeX engine

The build scripts auto-detect `xelatex > pdflatex > lualatex`. To force an
engine, edit the `pdf-engine` line in `defaults.yaml` or pass
`-LatexEngine pdflatex` to `build.ps1`.

> **Note:** Custom fonts (`mainfont`, `sansfont`, `monofont`) in `metadata.yaml`
> are only applied when using XeLaTeX or LuaLaTeX. pdflatex ignores them.

---

## Mermaid Diagrams — Strategy

The documentation contains 31 Mermaid diagrams. There are two rendering paths:

| Path | Tool | Quality | Setup |
|---|---|---|---|
| **Pre-processing (recommended)** | `mmdc` (Mermaid CLI) | Vector SVG images embedded in PDF | `npm install -g @mermaid-js/mermaid-cli` |
| **Fallback** | none | Diagrams shown as plain code blocks | No extra setup |

The build scripts automatically detect `mmdc` and use it if available.
Pass `--no-mermaid` / `-NoMermaid` to bypass pre-processing even when `mmdc` is installed.

**How pre-processing works:**

1. Each Markdown file containing ` ```mermaid ` blocks is passed to `mmdc`.
2. `mmdc` replaces each block with an SVG image reference and saves a
   processed copy to a temporary directory (`.tmp-mermaid/`).
3. Pandoc receives the processed copies; the temporary directory is deleted
   after the build completes.

**Alternative — pandoc filter:**

If `mmdc` is not available, you can use the `mermaid-filter` npm package as a
Pandoc filter:

```bash
npm install -g mermaid-filter
```

Then add to `defaults.yaml`:

```yaml
filters:
  - mermaid-filter
```

This is less reliable across platforms than pre-processing with `mmdc` but
requires no changes to the Markdown source files.

---

## Troubleshooting

**`Template eisvogel not found`**
Install Eisvogel (see Prerequisites above). Verify the file is at
`~/.local/share/pandoc/templates/eisvogel.latex` (Linux/macOS) or
`%APPDATA%\pandoc\templates\eisvogel.latex` (Windows).

**`Font "TeX Gyre Termes" not found`**
Install the fonts package:
- Ubuntu: `sudo apt install texlive-fonts-extra`
- macOS (MacTeX): already included
- Windows (MikTeX): auto-installs on first build
Alternatively, comment out the `mainfont`/`sansfont`/`monofont` lines in
`metadata.yaml` to use LaTeX defaults.

**`LaTeX Error: File 'xxx.sty' not found`**
A required LaTeX package is missing.
- MikTeX: packages install automatically; allow the package manager prompt.
- TeX Live: `sudo tlmgr install <package-name>`

**Build fails after adding a new doc**
1. Add the file path to `book.md`.
2. Verify the path is correct relative to `pdf/`.
3. Re-run the build script.

**Mermaid diagrams still show as code blocks**
Ensure `mmdc` is on your PATH: `mmdc --version`. On some systems Puppeteer
needs a Chromium download on first run; run `mmdc --help` once to trigger it.

**PDF is very large**
Mermaid SVGs embed all font data. To reduce file size, pass
`--outputFormat png` to `mmdc` instead of `svg` (edit the build script's
`--outputFormat` flag) or compress the final PDF:
`gs -dBATCH -dNOPAUSE -q -sDEVICE=pdfwrite -sOutputFile=out-compressed.pdf output/procurement-agent-docs.pdf`
