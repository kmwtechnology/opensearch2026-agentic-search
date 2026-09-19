-- Pandoc filter for the e-reader build.
-- NeoReader (Boox) ignores taps on in-page hyperlinks but its sidebar Contents
-- works, so: drop the hand-written "Table of Contents" section (the sidebar
-- carries the same list) and unwrap internal links to plain text so nothing
-- looks tappable when it isn't.

local function drop_toc_section(blocks)
  local out, skipping = {}, false
  for _, b in ipairs(blocks) do
    if b.t == "Header" and b.level == 2 then
      skipping = (pandoc.utils.stringify(b) == "Table of Contents")
    elseif skipping and b.t == "HorizontalRule" then
      skipping = false
      goto continue
    end
    if not skipping then table.insert(out, b) end
    ::continue::
  end
  return out
end

function Pandoc(doc)
  doc.blocks = drop_toc_section(doc.blocks)
  return doc
end

function Link(el)
  if el.target:sub(1, 1) == "#" then
    return el.content
  end
end
