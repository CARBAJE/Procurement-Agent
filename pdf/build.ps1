#Requires -Version 5.1
<#
.SYNOPSIS
    Generates the PDF technical documentation for the Procurement Agent project.

.DESCRIPTION
    Reads chapter order from book.md, optionally pre-processes Mermaid diagrams
    with mmdc, then invokes Pandoc with the Eisvogel LaTeX template to produce
    a professional PDF in pdf/output/.

.PARAMETER NoMermaid
    Skip Mermaid diagram pre-processing even if mmdc is available.

.PARAMETER Open
    Open the generated PDF in the default viewer after a successful build.

.PARAMETER LatexEngine
    Override the LaTeX engine (xelatex, pdflatex, lualatex).
    Default: auto-detect (xelatex preferred).

.EXAMPLE
    .\build.ps1
    .\build.ps1 -NoMermaid
    .\build.ps1 -Open
    .\build.ps1 -LatexEngine pdflatex
#>
[CmdletBinding()]
param(
    [switch]$NoMermaid,
    [switch]$Open,
    [ValidateSet("xelatex","pdflatex","lualatex")]
    [string]$LatexEngine = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ---- paths ----
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputDir   = Join-Path $ScriptDir "output"
$OutputFile  = Join-Path $OutputDir "procurement-agent-docs.pdf"
$Manifest    = Join-Path $ScriptDir "book.md"
$DefaultsFile= Join-Path $ScriptDir "defaults.yaml"
$TmpDir      = Join-Path $ScriptDir ".tmp-mermaid"

# ---- colour helpers ----
function Write-Info    { param($M) Write-Host "[INFO]  $M" -ForegroundColor Green  }
function Write-Warn    { param($M) Write-Host "[WARN]  $M" -ForegroundColor Yellow }
function Write-Err     { param($M) Write-Host "[ERROR] $M" -ForegroundColor Red    }
function Write-Section { param($M) Write-Host "`n==> $M" -ForegroundColor Cyan    }

function Test-Cmd {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# ==============================================================
# 1. CHECK REQUIREMENTS
# ==============================================================
Write-Section "Checking requirements"

# Pandoc
if (-not (Test-Cmd "pandoc")) {
    Write-Err "pandoc not found."
    Write-Err "  Install: https://pandoc.org/installing.html"
    Write-Err "  Or via winget: winget install JohnMacFarlane.Pandoc"
    exit 1
}
Write-Info "  $(pandoc --version | Select-Object -First 1)"

# LaTeX engine — auto-detect or use -LatexEngine parameter
$DetectedEngine = $LatexEngine
if (-not $DetectedEngine) {
    foreach ($eng in @("xelatex","pdflatex","lualatex")) {
        if (Test-Cmd $eng) { $DetectedEngine = $eng; break }
    }
}
if (-not $DetectedEngine) {
    Write-Err "No LaTeX engine found (tried xelatex, pdflatex, lualatex)."
    Write-Err "  Install MikTeX: https://miktex.org/download"
    Write-Err "  Or TeX Live:    https://tug.org/texlive/"
    exit 1
}
Write-Info "  LaTeX engine : $DetectedEngine"

if ($DetectedEngine -ne "xelatex") {
    Write-Warn "  Using $DetectedEngine. Custom font settings in metadata.yaml require XeLaTeX."
}

# Eisvogel template
$EisvogelpPaths = @(
    "$env:APPDATA\pandoc\templates\eisvogel.latex",
    "$env:USERPROFILE\.local\share\pandoc\templates\eisvogel.latex",
    "$env:ProgramFiles\Pandoc\templates\eisvogel.latex"
)
$EisvogelpFound = $false
foreach ($p in $EisvogelpPaths) {
    if (Test-Path $p) {
        Write-Info "  Eisvogel     : $p"
        $EisvogelpFound = $true
        break
    }
}
if (-not $EisvogelpFound) {
    Write-Warn "  Eisvogel not found in standard paths — Pandoc will search its data directory."
    Write-Warn "  If the build fails, install Eisvogel:"
    Write-Warn "    New-Item -ItemType Directory -Force `"`$env:APPDATA\pandoc\templates`""
    Write-Warn "    Invoke-WebRequest -Uri https://github.com/Wandmalfarbe/pandoc-latex-template/releases/latest/download/Eisvogel.tar.gz -OutFile eisvogel.tar.gz"
    Write-Warn "    tar -xzf eisvogel.tar.gz"
    Write-Warn "    Move-Item eisvogel.latex `"`$env:APPDATA\pandoc\templates\`""
}

# Mermaid CLI (optional)
$MmdicAvail = (Test-Cmd "mmdc") -and (-not $NoMermaid)
if ($MmdicAvail) {
    Write-Info "  Mermaid CLI  : found (mmdc)"
} elseif (-not $NoMermaid) {
    Write-Warn "  mermaid CLI (mmdc) not found — diagrams will render as code blocks."
    Write-Warn "  Install: npm install -g @mermaid-js/mermaid-cli"
}

# ==============================================================
# 2. PATCH defaults.yaml FOR DETECTED ENGINE
# ==============================================================
# Read the defaults, swap the pdf-engine line, write to a temp copy.
$DefaultsContent = Get-Content $DefaultsFile -Raw
$PatchedDefaults  = Join-Path $TmpDir "defaults-patched.yaml"

# ==============================================================
# 3. PARSE MANIFEST
# ==============================================================
Write-Section "Parsing chapter manifest: book.md"

$InputFiles = @()
foreach ($line in (Get-Content $Manifest)) {
    if ($line -match '^\s*#' -or $line.Trim() -eq '') { continue }
    $rel = $line.Trim().Replace('/', '\')
    $abs = Join-Path $ScriptDir $rel
    if (-not (Test-Path $abs)) {
        Write-Err "File not found: $abs"
        Write-Err "  (manifest entry: '$line')"
        exit 1
    }
    $InputFiles += $abs
}
Write-Info "  $($InputFiles.Count) chapters to compile"
foreach ($f in $InputFiles) { Write-Info "    $(Split-Path -Leaf $f)" }
# Keep a snapshot of the original source files — needed later for heading extraction.
$OriginalInputFiles = $InputFiles.Clone()

# ==============================================================
# 4. MERMAID PRE-PROCESSING
# ==============================================================
# Strategy: extract EACH mermaid block to an individual .mmd file and
# render to PNG independently.  This avoids the "one failure aborts the
# whole file" behaviour of mmdc's markdown mode, eliminates the need for
# rsvg-convert (SVG->PDF), and gives absolute image paths so pandoc
# never loses them regardless of working directory.
# ---------------------------------------------------------------
function Repair-MermaidDiagram {
    <#
    Fixes common Mermaid syntax issues that cause mmdc to crash:
      1. {identifier} inside flowchart edge labels |...|  -> bare identifier
         ALL bracket types ({}, [], ()) are reserved for node shapes.
         Strip them and keep the identifier text.
         Example:  BAP -->|PUBLISH beckn_results:{txn_id}| REDIS
                ->  BAP -->|PUBLISH beckn_results:txn_id| REDIS
      2. Literal \n inside flowchart edge labels |...| -> single space
         Example:  BAP -->|discover\n/ select| ONIX
      3. <Word> (bare HTML tags that are NOT <br/> / </...> / <!--) -> [Word]
         Puppeteer's HTML renderer fails on unrecognised tags.
         Example:  sha256=<digest>
      4. Participant names containing " :PORT" in sequence diagrams
         The space before the colon makes Mermaid interpret ":PORT" as a
         message separator token. Fix: replace " :DIGITS" with "-DIGITS"
         everywhere in the diagram (safe because URLs never have a space
         before their port colon).
         Example:  participant erp-adapter :8007  ->  erp-adapter-8007
    Preserves:
      - {text} in node shape definitions  (A{"decision"} diamond shapes)
      - \n in node labels  ["line1\nline2"]   (standard Mermaid line break)
      - <br/>  (valid Mermaid HTML line break in sequence/flowchart labels)
    #>
    param([string]$Content)

    # Fix 1: {identifier} in pipe-based edge labels -> bare identifier
    # ALL bracket types ({}, [], ()) are invalid inside Mermaid edge labels —
    # they trigger shape tokens (diamond, rectangle, stadium).  Strip them.
    # Example: |PUBLISH beckn_results:{txn_id}|  ->  |PUBLISH beckn_results:txn_id|
    $Content = [regex]::Replace(
        $Content,
        '(\|[^|]*)\{([A-Za-z_][A-Za-z0-9_:]*)\}([^|]*\|)',
        '$1$2$3'
    )

    # Fix 2: bare \n inside pipe-based edge labels -> space
    $Content = [regex]::Replace(
        $Content,
        '(\|[^|]*)\\n([^|]*\|)',
        '$1 $2'
    )

    # Fix 3: <Word> that is NOT <br/>, </...>, <!-- ...-->
    $Content = [regex]::Replace(
        $Content,
        '<(?!br[\s/])(?![/!])([A-Za-z][A-Za-z0-9_-]*)>',
        '[$1]'
    )

    # Fix 4: " :PORT" (space + colon + 3-5 digit port) -> "-PORT"
    # Applies to the entire diagram so both participant declarations and
    # message-line actor references are updated consistently.
    $Content = [regex]::Replace(
        $Content,
        ' :(\d{3,5})\b',
        '-$1'
    )

    return $Content
}

function Invoke-MermaidBlocks {
    param(
        [string]$SrcPath,       # original .md file
        [string]$OutDir,        # temp directory for .mmd and .png files
        [string]$PuppCfgPath    # puppeteer.json — passed to mmdc
    )

    $lines    = Get-Content $SrcPath -Encoding UTF8
    $outLines = [System.Collections.Generic.List[string]]::new()
    $base     = [System.IO.Path]::GetFileNameWithoutExtension($SrcPath)
    $idx      = 0
    $inBlock  = $false
    $blockBuf = [System.Collections.Generic.List[string]]::new()
    $okCount  = 0
    $failCount = 0

    foreach ($line in $lines) {
        if (-not $inBlock) {
            # Detect mermaid fence: line is exactly ```mermaid (no trailing spaces)
            if ($line.TrimEnd() -eq '```mermaid') {
                $inBlock = $true
                $blockBuf.Clear()
            } else {
                $outLines.Add($line)
            }
        } else {
            if ($line.TrimEnd() -eq '```') {
                # End of block — render this individual diagram
                $inBlock = $false
                $idx++

                $mmdFile = Join-Path $OutDir "$base-$idx.mmd"
                $pngFile = Join-Path $OutDir "$base-$idx.png"

                $diagramText = Repair-MermaidDiagram ($blockBuf -join "`n")
                [System.IO.File]::WriteAllText(
                    $mmdFile,
                    $diagramText,
                    [System.Text.UTF8Encoding]::new($false)
                )

                $mmdcArgs = @(
                    '--input',  $mmdFile,
                    '--output', $pngFile,
                    '--outputFormat', 'png',
                    '--backgroundColor', 'white',
                    '--scale', '2'
                )
                if (Test-Path $PuppCfgPath) {
                    $mmdcArgs += '--puppeteerConfigFile', $PuppCfgPath
                }

                $mmOut = & mmdc @mmdcArgs 2>&1
                $rc    = $LASTEXITCODE

                if ($rc -eq 0 -and (Test-Path $pngFile)) {
                    $okCount++
                    # Use forward slashes — pandoc accepts them on Windows
                    $imgUri = $pngFile.Replace('\', '/')
                    $outLines.Add('')
                    $outLines.Add("![$base diagram $idx]($imgUri)")
                    $outLines.Add('')
                } else {
                    $failCount++
                    $firstErr = ($mmOut | Where-Object { $_ -notmatch '^\s*$' } | Select-Object -First 1)
                    Write-Warn "    diagram $idx failed$(if ($firstErr) { ': ' + $firstErr })"
                    # Keep original mermaid block as code (renders as code block in PDF)
                    $outLines.Add('```mermaid')
                    foreach ($bl in $blockBuf) { $outLines.Add($bl) }
                    $outLines.Add('```')
                }
            } else {
                $blockBuf.Add($line)
            }
        }
    }

    return $outLines, $okCount, $failCount
}

# ==============================================================
# Cross-document link resolution helpers
# ==============================================================
function Get-GfmAnchor {
    <#
    Reproduces GitHub Flavored Markdown heading-to-anchor rules.
    Must match the gfm-ids.lua Lua filter exactly:
      1. Strip non-ASCII bytes (so em dashes etc. are removed cleanly)
      2. Lowercase
      3. Drop everything except ASCII alphanumerics, spaces, and hyphens
      4. Each whitespace char -> one hyphen (NO collapsing: "a  b" -> "a--b")
      5. Trim leading/trailing hyphens
    #>
    param([string]$HeadingText)
    # Strip non-ASCII chars (encode to bytes, keep only 0x00-0x7F, re-decode)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($HeadingText)
    $ascii = ($bytes | Where-Object { $_ -lt 128 } | ForEach-Object { [char]$_ }) -join ''
    $t = $ascii.ToLower()
    $t = [regex]::Replace($t, '[^a-z0-9\s\-]', '')
    # Non-collapsing: replace each individual whitespace char with a hyphen
    $t = [regex]::Replace($t, '\s', '-')
    $t = $t.Trim('-')
    if ($t -eq '') { return 'section' }
    return $t
}

function Build-HeadingAnchorMap {
    <#
    Reads the first Markdown heading from each source file and returns a
    hashtable mapping basename-without-extension -> GFM anchor string.
    Used to resolve bare-filename links like [Architecture](ARCHITECTURE.md).
    #>
    param([string[]]$FilePaths)
    $map = @{}
    foreach ($f in $FilePaths) {
        $base = [System.IO.Path]::GetFileNameWithoutExtension($f)
        $firstHeading = Get-Content $f -Encoding UTF8 |
            Where-Object { $_ -match '^#{1,6}\s' } |
            Select-Object -First 1
        if ($firstHeading) {
            $text = $firstHeading -replace '^#{1,6}\s+', ''
            # Strip inline markdown formatting before anchor computation
            $text = $text -replace '\*\*([^*]+)\*\*', '$1'
            $text = $text -replace '\*([^*]+)\*',     '$1'
            $text = $text -replace '`([^`]+)`',       '$1'
            $text = $text -replace '\[([^\]]+)\]\([^)]+\)', '$1'
            $map[$base] = Get-GfmAnchor $text
        }
    }
    return $map
}

function Resolve-CrossDocLinks {
    <#
    Rewrites relative .md links so they work as internal PDF anchors:
      [Architecture](ARCHITECTURE.md)          -> [Architecture](#architecture)
      [ADR-0001](ARCHITECTURE.md#some-section) -> [ADR-0001](#some-section)
    Links to files outside the compilation set (e.g. ../docs/...) are left as-is.
    #>
    param([string]$Content, [hashtable]$HeadingMap)

    # Pattern captures:
    #   Group 1 — link text
    #   Group 2 — optional directory prefix (discarded)
    #   Group 3 — base filename without extension
    #   Group 4 — optional fragment (without leading #)
    $pattern = '\[([^\]]*)\]\((?:[^)]*?/)?([A-Za-z0-9_-]+)\.md(?:#([^)"]*))?\)'

    $Content = [regex]::Replace($Content, $pattern, {
        param($m)
        $text     = $m.Groups[1].Value
        $fname    = $m.Groups[2].Value
        $fragment = $m.Groups[3].Value

        if (-not $HeadingMap.ContainsKey($fname)) {
            return $m.Value   # not in compilation set — keep original
        }

        if ($fragment) {
            return "[$text](#$fragment)"
        } else {
            return "[$text](#$($HeadingMap[$fname]))"
        }
    })

    return $Content
}

if ($MmdicAvail) {
    Write-Section "Pre-processing Mermaid diagrams (individual extraction)"
    if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Path $TmpDir | Out-Null }

    $PuppCfgPath = Join-Path $ScriptDir "puppeteer.json"
    $ProcessedFiles = @()
    $totalOk   = 0
    $totalFail = 0

    foreach ($src in $InputFiles) {
        $baseName = Split-Path -Leaf $src
        $content  = Get-Content $src -Raw -Encoding UTF8

        if ($content -match '```mermaid') {
            Write-Info "  $baseName"
            $dst = Join-Path $TmpDir $baseName

            $outLines, $ok, $fail = Invoke-MermaidBlocks -SrcPath $src -OutDir $TmpDir -PuppCfgPath $PuppCfgPath

            [System.IO.File]::WriteAllLines($dst, $outLines, [System.Text.UTF8Encoding]::new($false))
            $ProcessedFiles += $dst
            $totalOk   += $ok
            $totalFail += $fail

            if ($ok -gt 0 -and $fail -eq 0) {
                Write-Info "    $ok diagram(s) -> PNG"
            } elseif ($ok -gt 0) {
                Write-Warn "    $ok diagram(s) -> PNG, $fail diagram(s) -> code block"
            } else {
                Write-Warn "    all $fail diagram(s) failed -> code blocks"
            }
        } else {
            $ProcessedFiles += $src
        }
    }

    $InputFiles = $ProcessedFiles
    Write-Info "  Total: $totalOk diagram(s) rendered as PNG, $totalFail as code blocks"
} elseif ($NoMermaid) {
    Write-Info "Mermaid pre-processing skipped (-NoMermaid)"
} else {
    Write-Info "Mermaid pre-processing skipped (mmdc not available)"
}

# ==============================================================
# 5. CROSS-DOCUMENT LINK RESOLUTION
# ==============================================================
# Rewrites [Text](FILENAME.md) and [Text](FILENAME.md#section) links to
# internal PDF anchors so they navigate correctly in the compiled PDF.
# Uses the original source files (before Mermaid expansion) to build
# the heading map so that anchor computation is stable.
Write-Section "Resolving cross-document links"
$HeadingMap = Build-HeadingAnchorMap -FilePaths $OriginalInputFiles
Write-Info "  Heading map built for $($HeadingMap.Count) file(s)"

if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Path $TmpDir | Out-Null }

$LinkedFiles = @()
$rewriteCount = 0
foreach ($f in $InputFiles) {
    $content  = [System.IO.File]::ReadAllText($f, [System.Text.UTF8Encoding]::new($false))
    $resolved = Resolve-CrossDocLinks -Content $content -HeadingMap $HeadingMap
    if ($resolved -ne $content) {
        $rewriteCount++
        $dst = Join-Path $TmpDir (Split-Path -Leaf $f)
        [System.IO.File]::WriteAllText($dst, $resolved, [System.Text.UTF8Encoding]::new($false))
        $LinkedFiles += $dst
    } else {
        $LinkedFiles += $f
    }
}
$InputFiles = $LinkedFiles
Write-Info "  $rewriteCount file(s) had cross-document links rewritten"

# ==============================================================
# 6. BUILD PDF
# ==============================================================
Write-Section "Building PDF"

if (-not (Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir | Out-Null }

# Write a patched defaults.yaml with the detected engine
if (-not (Test-Path $TmpDir)) { New-Item -ItemType Directory -Path $TmpDir | Out-Null }
$PatchedContent = $DefaultsContent -replace 'pdf-engine:\s*\S+', "pdf-engine: $DetectedEngine"
[System.IO.File]::WriteAllText($PatchedDefaults, $PatchedContent, [System.Text.UTF8Encoding]::new($false))

Write-Info "  Output: $OutputFile"

# Build the resource-path list explicitly.
# NOTE: a CLI --resource-path OVERRIDES the one in defaults.yaml, so ALL
#       paths must be listed here.  Mermaid PNGs use absolute paths in the
#       processed markdown, so pandoc resolves them without needing TmpDir.
$ResPaths = @(
    (Join-Path $ScriptDir "assets"),
    (Join-Path $ScriptDir "..\project_docs\documentation")
)
$ResourcePathArg = $ResPaths -join ";"

# Change to pdf/ so relative paths in defaults.yaml resolve correctly
Push-Location $ScriptDir
try {
    $PandocArgs = @(
        "--defaults",       $PatchedDefaults,
        "--resource-path",  $ResourcePathArg,
        "--output",         $OutputFile
    ) + $InputFiles

    & pandoc @PandocArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Pandoc exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# ==============================================================
# 6. CLEANUP AND REPORT
# ==============================================================
if (Test-Path $TmpDir) { Remove-Item -Recurse -Force $TmpDir }

if (Test-Path $OutputFile) {
    $kb = [math]::Round((Get-Item $OutputFile).Length / 1KB, 0)
    Write-Host ""
    Write-Host "Build successful!" -ForegroundColor Green -BackgroundColor Black
    Write-Info "  PDF  : $OutputFile"
    Write-Info "  Size : ${kb} KB"
    if ($Open) {
        Start-Process $OutputFile
    }
} else {
    Write-Err "Build failed — output file was not created."
    exit 1
}
