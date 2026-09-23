-- gfm-ids.lua
-- Assigns GFM-style heading IDs to every heading in the document.
--
-- Pandoc's standard auto_identifiers strips leading digits/punctuation, so
-- "## 4. Async Discovery Decoupling" becomes "async-discovery-decoupling".
-- GitHub renders the same heading with ID "4-async-discovery-decoupling".
-- Cross-references in the docs were written for GitHub, so they expect GFM IDs.
--
-- GFM algorithm (matches github.com/jch/html-pipeline toc_filter.rb):
--   1. Lowercase
--   2. Drop every character except alphanumerics, spaces, and hyphens
--   3. Convert each whitespace character to a hyphen (no collapsing)
--   4. Strip leading / trailing hyphens
--
-- Used together with -auto_identifiers in the from: format string so that
-- Pandoc's built-in auto-assignment doesn't compete with this filter.
--
-- Non-ASCII handling: Pandoc's Lua runtime is Lua 5.4, but string patterns
-- operate byte-by-byte.  Multi-byte UTF-8 characters (e.g. the em dash
-- U+2014 = E2 80 94) are stripped at the byte level before lowercasing so
-- that no garbage bytes survive into the label.  The surrounding ASCII spaces
-- are preserved and each converts to a hyphen, producing the correct
-- double-hyphen for "word — word" patterns.

local function gfm_anchor(inlines)
  -- pandoc.utils.stringify handles all inline types and returns proper UTF-8
  local s = pandoc.utils.stringify(inlines)
  -- 1. Strip all non-ASCII bytes (bytes 0x80–0xFF).
  --    This removes multi-byte UTF-8 characters byte-by-byte without
  --    corrupting the ASCII portions of the string.
  s = s:gsub("[\128-\255]", "")
  -- 2. Lowercase (safe on ASCII-only string after step 1)
  s = s:lower()
  -- 3. Drop every character that is not an ASCII alphanumeric, space, or hyphen
  s = s:gsub("[^%w%s%-]", "")
  -- 4. Each whitespace character → one hyphen (no collapsing: "a  b" → "a--b")
  s = s:gsub("%s", "-")
  -- 5. Clean up leading/trailing hyphens
  s = s:gsub("^%-+", ""):gsub("%-+$", "")
  return s ~= "" and s or "section"
end

function Header(el)
  el.identifier = gfm_anchor(el.content)
  return el
end
