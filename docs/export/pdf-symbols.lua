-- PDF exports only (`./dev.ps1 docs-export`): the LaTeX fonts in the pandoc image have no
-- glyph for these characters, so the PDF would silently leave them out. They are written out
-- instead; the Word copies keep the characters, since Word uses the computer's own fonts.
local written = {
  ["₹"] = "Rs ",
  ["≤"] = "<=",
  ["∉"] = "not in",
  ["▼"] = "down ",
}

local function write_out(text)
  for symbol, words in pairs(written) do
    text = text:gsub(symbol, words)
  end
  return text
end

function Str(el)
  el.text = write_out(el.text)
  return el
end

function Code(el)
  el.text = write_out(el.text)
  return el
end

function CodeBlock(el)
  el.text = write_out(el.text)
  return el
end
