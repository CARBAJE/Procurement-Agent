# Procurement Agent — PDF Chapter Manifest
#
# This file defines the order in which documentation chapters are assembled
# into the final PDF. Build scripts read this file line by line:
#   - Lines starting with # are comments (ignored).
#   - Blank lines are ignored.
#   - All other lines are file paths relative to the pdf/ directory.
#
# Edit this file to add, remove, or reorder chapters.
# After editing, re-run build.ps1 (Windows) or build.sh (Linux/macOS).
#
# NOTE: VALIDATION_REPORT.md is intentionally excluded from the PDF
#       (it is an internal build artefact, not end-user documentation).
#
# ============================================================
# PART 1 — INTRODUCTION
# ============================================================
../project_docs/documentation/README.md
../project_docs/documentation/PROJECT_OVERVIEW.md
#
# ============================================================
# PART 2 — ARCHITECTURE
# ============================================================
../project_docs/documentation/ARCHITECTURE.md
../project_docs/documentation/SYSTEM_DESIGN.md
../project_docs/documentation/DATA_FLOW.md
#
# ============================================================
# PART 3 — SETUP AND CONFIGURATION
# ============================================================
../project_docs/documentation/INSTALLATION.md
../project_docs/documentation/CONFIGURATION.md
#
# ============================================================
# PART 4 — REFERENCE
# ============================================================
../project_docs/documentation/DATABASE.md
../project_docs/documentation/SECURITY.md
#
# ============================================================
# PART 5 — OPERATIONS
# ============================================================
../project_docs/documentation/DEPLOYMENT.md
../project_docs/documentation/TESTING.md
#
# ============================================================
# PART 6 — DEVELOPMENT
# ============================================================
../project_docs/documentation/DEVELOPMENT_GUIDE.md
../project_docs/documentation/CONTRIBUTING.md
../project_docs/documentation/TROUBLESHOOTING.md
#
# ============================================================
# APPENDIX
# ============================================================
../project_docs/documentation/API_REFERENCE.md
../project_docs/documentation/GLOSSARY.md
