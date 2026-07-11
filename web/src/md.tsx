import { type ReactNode } from 'react'

// A deliberately small Markdown renderer for the maintenance agent's answers, which use only:
// paragraphs, `- ` bullet lists, **bold**, `code`, _italic_, and [text](url). Every node is
// built as React — no raw HTML is ever interpreted, so there is no injection surface.
//
// The italic rule requires a non-word boundary around the underscores so wheel/position codes
// like `mlg_r_inbd` in plain text are never mistaken for emphasis.
const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))|((?<![\w])_[^_]+_(?![\w]))/g

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  let key = 0
  for (const m of text.matchAll(INLINE)) {
    const idx = m.index ?? 0
    if (idx > last) nodes.push(text.slice(last, idx))
    const tok = m[0]
    if (tok.startsWith('`')) {
      nodes.push(
        <code key={key++} className="rounded bg-[var(--primary-soft)] px-1 py-0.5 text-[var(--primary)]">
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('**')) {
      nodes.push(
        <strong key={key++} className="font-semibold text-[var(--ink)]">
          {tok.slice(2, -2)}
        </strong>,
      )
    } else if (tok.startsWith('[')) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)
      const label = mm?.[1] ?? tok
      const href = mm?.[2] ?? ''
      const safe = /^(https?:\/\/|\/)/.test(href)
      nodes.push(
        safe ? (
          <a key={key++} href={href} target="_blank" rel="noreferrer" className="text-[var(--primary)] underline">
            {label}
          </a>
        ) : (
          label
        ),
      )
    } else {
      nodes.push(<em key={key++}>{tok.slice(1, -1)}</em>)
    }
    last = idx + tok.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let bullets: string[] = []
  let key = 0

  const flush = () => {
    if (!bullets.length) return
    const items = bullets
    blocks.push(
      <ul key={key++} className="flex flex-col gap-1">
        {items.map((li, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-[0.15em] text-[var(--primary)]">▸</span>
            <span className="flex-1">{renderInline(li)}</span>
          </li>
        ))}
      </ul>,
    )
    bullets = []
  }

  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    if (/^\s*[-*]\s+/.test(line)) {
      bullets.push(line.replace(/^\s*[-*]\s+/, ''))
    } else if (line.trim() === '') {
      flush()
    } else {
      flush()
      blocks.push(
        <p key={key++} className="leading-relaxed">
          {renderInline(line)}
        </p>,
      )
    }
  }
  flush()

  return <div className="flex flex-col gap-2 text-sm text-[var(--ink-2)]">{blocks}</div>
}
