#!/usr/bin/env bash
# ==============================================================
# build.sh — PDF build script for Linux and macOS
# Usage:
#   ./build.sh              # Full build with Mermaid pre-processing
#   ./build.sh --no-mermaid # Skip Mermaid pre-processing
#   ./build.sh --open       # Open the PDF after building
# ==============================================================
set -euo pipefail

# ---- parse flags ----
SKIP_MERMAID=false
OPEN_AFTER=false
for arg in "$@"; do
    case "$arg" in
        --no-mermaid) SKIP_MERMAID=true ;;
        --open)       OPEN_AFTER=true   ;;
        --help|-h)
            sed -n '2,6p' "$0" | sed 's/^# //'
            exit 0 ;;
    esac
done

# ---- paths ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
OUTPUT_FILE="$OUTPUT_DIR/procurement-agent-docs.pdf"
MANIFEST="$SCRIPT_DIR/book.md"
DEFAULTS="$SCRIPT_DIR/defaults.yaml"
TMP_DIR="$SCRIPT_DIR/.tmp-mermaid"

# ---- colour helpers ----
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi
info()    { printf "${GREEN}[INFO]${NC}  %s\n"    "$*"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n"   "$*"; }
error()   { printf "${RED}[ERROR]${NC} %s\n"  "$*" >&2; }
section() { printf "\n${BOLD}${CYAN}==> %s${NC}\n" "$*"; }

# ==============================================================
# 1. CHECK REQUIREMENTS
# ==============================================================
section "Checking requirements"

# Pandoc
if ! command -v pandoc &>/dev/null; then
    error "pandoc not found."
    error "  Install: https://pandoc.org/installing.html"
    error "  Ubuntu/Debian: sudo apt install pandoc"
    error "  macOS:         brew install pandoc"
    exit 1
fi
PANDOC_VER=$(pandoc --version | head -1)
PANDOC_MINOR=$(pandoc --version | head -1 | grep -oP '\d+\.\d+' | head -1 | cut -d. -f2)
if [ "${PANDOC_MINOR:-0}" -lt 8 ] 2>/dev/null; then
    warn "Pandoc version may be too old (< 2.8). Defaults files require 2.8+."
fi
info "  $PANDOC_VER"

# LaTeX engine
LATEX_ENGINE=""
for engine in xelatex pdflatex lualatex; do
    if command -v "$engine" &>/dev/null; then
        LATEX_ENGINE="$engine"
        break
    fi
done
if [ -z "$LATEX_ENGINE" ]; then
    error "No LaTeX engine found (tried xelatex, pdflatex, lualatex)."
    error "  Ubuntu/Debian: sudo apt install texlive-xetex texlive-fonts-extra texlive-latex-extra"
    error "  macOS:         brew install --cask mactex"
    exit 1
fi
info "  LaTeX engine : $LATEX_ENGINE"

# Update defaults.yaml to use detected engine
if [ "$LATEX_ENGINE" != "xelatex" ]; then
    warn "  Using $LATEX_ENGINE — metadata.yaml font settings will be ignored (XeLaTeX only)."
fi

# Eisvogel template
EISVOGEL_FOUND=false
for dir in \
    "$HOME/.local/share/pandoc/templates" \
    "$HOME/Library/Application Support/pandoc/templates" \
    "/usr/share/pandoc/data/templates" \
    "$(pandoc --version 2>/dev/null | grep -oP 'data-dir: \K.*' | head -1)/templates"
do
    if [ -f "$dir/eisvogel.latex" ] 2>/dev/null; then
        EISVOGEL_FOUND=true
        info "  Eisvogel     : $dir/eisvogel.latex"
        break
    fi
done
if ! $EISVOGEL_FOUND; then
    error "Eisvogel template not found in any standard Pandoc template directory."
    error "  Install instructions:"
    error "    TMPL_DIR=\"\$HOME/.local/share/pandoc/templates\""
    error "    mkdir -p \"\$TMPL_DIR\""
    error "    curl -sL https://github.com/Wandmalfarbe/pandoc-latex-template/releases/latest/download/Eisvogel.tar.gz \\"
    error "      | tar xz -C \"\$TMPL_DIR\""
    exit 1
fi

# Mermaid CLI (optional)
MMDC_AVAILABLE=false
if ! $SKIP_MERMAID; then
    if command -v mmdc &>/dev/null; then
        MMDC_AVAILABLE=true
        info "  Mermaid CLI  : $(mmdc --version 2>/dev/null | head -1 || echo 'found')"
    else
        warn "  mermaid CLI (mmdc) not found — diagrams will render as code blocks."
        warn "  Install: npm install -g @mermaid-js/mermaid-cli"
    fi
fi

# ==============================================================
# 2. PARSE MANIFEST
# ==============================================================
section "Parsing chapter manifest: book.md"

INPUT_FILES=()
while IFS= read -r line; do
    # Skip comments and blank lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # Resolve path relative to pdf/ directory
    abs="$SCRIPT_DIR/$line"
    if [ ! -f "$abs" ]; then
        error "File not found: $abs"
        error "  (manifest entry: '$line')"
        exit 1
    fi
    INPUT_FILES+=("$abs")
done < "$MANIFEST"

info "  ${#INPUT_FILES[@]} chapters to compile"
for f in "${INPUT_FILES[@]}"; do
    info "    $(basename "$f")"
done

# ==============================================================
# 3. MERMAID PRE-PROCESSING
# ==============================================================
if $MMDC_AVAILABLE; then
    section "Pre-processing Mermaid diagrams"
    mkdir -p "$TMP_DIR"

    PROCESSED_FILES=()
    for src in "${INPUT_FILES[@]}"; do
        base=$(basename "$src")
        dst="$TMP_DIR/$base"
        if grep -q '```mermaid' "$src" 2>/dev/null; then
            info "  Processing: $base"
            MMDC_ERR=$(mmdc \
                --input  "$src" \
                --output "$dst" \
                --outputFormat svg \
                --backgroundColor white \
                2>&1) && rc=0 || rc=$?
            if [ "$rc" -eq 0 ]; then
                PROCESSED_FILES+=("$dst")
            else
                warn "  mmdc failed for $base (exit $rc) — diagrams will be code blocks"
                FIRST_ERR=$(echo "$MMDC_ERR" | grep -v '^\s*$' | head -1)
                [ -n "$FIRST_ERR" ] && warn "    $FIRST_ERR"
                PROCESSED_FILES+=("$src")
            fi
        else
            PROCESSED_FILES+=("$src")
        fi
    done
    INPUT_FILES=("${PROCESSED_FILES[@]}")
    info "  Mermaid pre-processing complete"
else
    if ! $SKIP_MERMAID; then
        info "  Skipping Mermaid pre-processing (mmdc not available)"
    else
        info "  Mermaid pre-processing skipped (--no-mermaid)"
    fi
fi

# ==============================================================
# 4. BUILD PDF
# ==============================================================
section "Building PDF"

mkdir -p "$OUTPUT_DIR"
info "  Output: $OUTPUT_FILE"

# Change to pdf/ directory so all relative paths in defaults.yaml resolve correctly
cd "$SCRIPT_DIR"

# Build the resource-path list explicitly.
# A CLI --resource-path OVERRIDES the one in defaults.yaml, so we must
# enumerate ALL paths here. The TMP_DIR entry is added when mmdc was used
# so that pandoc can find the SVG files mmdc writes alongside the processed
# markdown (e.g. DATA_FLOW-1.svg, ARCHITECTURE-1.svg, ...).
RES_PATHS="$SCRIPT_DIR/assets:$SCRIPT_DIR/../project_docs/documentation"
if $MMDC_AVAILABLE && [ -d "$TMP_DIR" ]; then
    RES_PATHS="$RES_PATHS:$TMP_DIR"
    info "  Resource path includes: $TMP_DIR (Mermaid SVGs)"
fi

pandoc \
    --defaults      "$DEFAULTS" \
    --resource-path "$RES_PATHS" \
    --output        "$OUTPUT_FILE" \
    "${INPUT_FILES[@]}"

# ==============================================================
# 5. CLEANUP AND REPORT
# ==============================================================
if [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
fi

if [ -f "$OUTPUT_FILE" ]; then
    if command -v du &>/dev/null; then
        SIZE=$(du -sh "$OUTPUT_FILE" | cut -f1)
    else
        SIZE="unknown size"
    fi
    printf "\n${GREEN}${BOLD}Build successful!${NC}\n"
    info "  PDF  : $OUTPUT_FILE"
    info "  Size : $SIZE"
    if $OPEN_AFTER; then
        if command -v xdg-open &>/dev/null; then
            xdg-open "$OUTPUT_FILE" &
        elif command -v open &>/dev/null; then
            open "$OUTPUT_FILE"
        fi
    fi
else
    error "Build failed — output file was not created."
    exit 1
fi
