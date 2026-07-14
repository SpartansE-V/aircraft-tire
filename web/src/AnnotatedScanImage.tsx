/** Renders a scan image with 2D overlays from metadata.json.

Display rules:
  - crack         → geometry only (no "crack" text)
  - tread-shallow → geometry + "shallow" label
  - wheel / tread → omitted by the API

Pass ``rotate={90}`` to stand a wide flatten strip upright (CW).

Crack polygons share ``defect_label`` with TireViewer 3D overlays — clicking one
highlights the matching crack on both views.
*/

import { useEffect, useRef, useState } from 'react'

export type ScanAnnotation2D = {
  category: 'crack' | 'tread-shallow'
  label: string | null
  /** Matches Defect.label (e.g. crack-circle-26) for 2D↔3D selection sync. */
  defect_label?: string | null
  bbox: [number, number, number, number] | number[]
  center: { x: number; y: number }
  segmentation: number[][]
}

export type AnnotatedScanImageData = {
  url: string
  width: number
  height: number
  annotations: ScanAnnotation2D[]
}

const STROKE = {
  crack: '#ef4444',
  'tread-shallow': '#eab308',
} as const

const SELECTED = '#22d3ee'

export default function AnnotatedScanImage({
  image,
  alt,
  className = '',
  rotate = 0,
  fill = false,
  selectedLabel = null,
  onSelectCrack,
}: {
  image: AnnotatedScanImageData
  alt?: string
  className?: string
  /** Degrees clockwise — use 90 to stand flatten images upright. */
  rotate?: 0 | 90
  /** Stretch to parent instead of intrinsic aspect ratio (match a column height). */
  fill?: boolean
  selectedLabel?: string | null
  onSelectCrack?: (label: string | null) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [natural, setNatural] = useState({ w: image.width, h: image.height })
  const selectedRef = useRef(selectedLabel)
  selectedRef.current = selectedLabel
  const onSelectRef = useRef(onSelectCrack)
  onSelectRef.current = onSelectCrack

  useEffect(() => {
    setNatural({ w: image.width, h: image.height })
    const img = new Image()
    img.onload = () => {
      setNatural((prev) => ({
        w: prev.w || img.naturalWidth,
        h: prev.h || img.naturalHeight,
      }))
    }
    img.src = image.url
  }, [image.url, image.width, image.height])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return

    const srcW = natural.w
    const srcH = natural.h
    if (srcW < 1 || srcH < 1) return

    const paint = () => {
      const w = wrap.clientWidth
      const h = wrap.clientHeight
      if (w < 1 || h < 1) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      const bitmap = new Image()
      bitmap.onload = () => {
        ctx.save()
        if (rotate === 90) {
          // Stand wide strip upright: source (srcW×srcH) → display (w×h) with w~srcH, h~srcW.
          ctx.translate(w, 0)
          ctx.rotate(Math.PI / 2)
          ctx.drawImage(bitmap, 0, 0, h, w)
          drawAnnotations(ctx, image.annotations, h / srcW, w / srcH, selectedRef.current)
        } else {
          ctx.drawImage(bitmap, 0, 0, w, h)
          drawAnnotations(ctx, image.annotations, w / srcW, h / srcH, selectedRef.current)
        }
        ctx.restore()
      }
      bitmap.src = image.url
    }

    paint()
    const ro = new ResizeObserver(paint)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [image, natural, rotate, selectedLabel])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap || !onSelectCrack) return

    const srcW = natural.w
    const srcH = natural.h
    if (srcW < 1 || srcH < 1) return

    const onClick = (e: MouseEvent) => {
      const rect = wrap.getBoundingClientRect()
      const dx = e.clientX - rect.left
      const dy = e.clientY - rect.top
      const w = rect.width
      const h = rect.height
      const src = displayToSource(dx, dy, w, h, srcW, srcH, rotate)
      if (!src) {
        onSelectRef.current?.(null)
        return
      }
      const hit = hitTestAnnotation(image.annotations, src.x, src.y)
      onSelectRef.current?.(hit === selectedRef.current ? null : hit)
    }

    canvas.style.cursor = image.annotations.some((a) => a.defect_label) ? 'crosshair' : ''
    canvas.addEventListener('click', onClick)
    return () => canvas.removeEventListener('click', onClick)
  }, [image, natural, rotate, onSelectCrack])

  // Rotated 90°: swap aspect so the strip stands tall (ignored when fill=true).
  const ratio =
    natural.w > 0 && natural.h > 0
      ? rotate === 90
        ? `${natural.h} / ${natural.w}`
        : `${natural.w} / ${natural.h}`
      : '1 / 1'

  return (
    <div
      ref={wrapRef}
      className={`relative overflow-hidden border border-[var(--line)] bg-[var(--panel)] ${
        fill ? 'h-full w-full' : 'w-full'
      } ${className}`}
      style={fill ? undefined : { aspectRatio: ratio }}
      role="img"
      aria-label={alt ?? ''}
    >
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
    </div>
  )
}

/** Map display click → source image coords (accounts for rotate=90). */
function displayToSource(
  dx: number,
  dy: number,
  w: number,
  h: number,
  srcW: number,
  srcH: number,
  rotate: 0 | 90,
): { x: number; y: number } | null {
  if (w < 1 || h < 1) return null
  if (rotate === 90) {
    // Inverse of translate(w,0) + rotate(π/2) + scale(h/srcW, w/srcH).
    return { x: (dy * srcW) / h, y: ((w - dx) * srcH) / w }
  }
  return { x: (dx * srcW) / w, y: (dy * srcH) / h }
}

function pointInRing(px: number, py: number, ring: number[]): boolean {
  // Ray casting on flat [x0,y0,x1,y1,...] polygon.
  let inside = false
  const n = Math.floor(ring.length / 2)
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = ring[i * 2]
    const yi = ring[i * 2 + 1]
    const xj = ring[j * 2]
    const yj = ring[j * 2 + 1]
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

function hitTestAnnotation(annotations: ScanAnnotation2D[], x: number, y: number): string | null {
  // Prefer cracks; last drawn (later in list) wins when overlapping.
  let hit: string | null = null
  for (const ann of annotations) {
    if (!ann.defect_label) continue
    let inside = false
    for (const ring of ann.segmentation) {
      if (ring.length >= 6 && pointInRing(x, y, ring)) {
        inside = true
        break
      }
    }
    if (!inside && ann.bbox.length >= 4) {
      const [bx, by, bw, bh] = ann.bbox
      inside = x >= bx && x <= bx + bw && y >= by && y <= by + bh
    }
    if (inside) hit = ann.defect_label
  }
  return hit
}

function drawAnnotations(
  ctx: CanvasRenderingContext2D,
  annotations: ScanAnnotation2D[],
  sx: number,
  sy: number,
  selectedLabel: string | null,
) {
  // Draw non-selected first, then the selected polygon on top so the full fill reads clearly.
  const ordered = [...annotations].sort((a, b) => {
    const aSel = a.defect_label && a.defect_label === selectedLabel ? 1 : 0
    const bSel = b.defect_label && b.defect_label === selectedLabel ? 1 : 0
    return aSel - bSel
  })

  for (const ann of ordered) {
    const isSelected = !!ann.defect_label && ann.defect_label === selectedLabel
    const dimOthers = selectedLabel != null && !isSelected && ann.category === 'crack'
    const color = isSelected ? SELECTED : STROKE[ann.category]
    ctx.globalAlpha = dimOthers ? 0.22 : 1
    ctx.strokeStyle = color
    // Selected: fill the entire polygon solidly so 3D→2D link is obvious.
    ctx.fillStyle = isSelected ? `${SELECTED}99` : `${color}33`
    ctx.lineWidth = isSelected ? 4 : ann.category === 'crack' ? 2 : 1.5

    let drew = false
    for (const ring of ann.segmentation) {
      if (ring.length < 6) continue
      ctx.beginPath()
      for (let i = 0; i + 1 < ring.length; i += 2) {
        const x = ring[i] * sx
        const y = ring[i + 1] * sy
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.closePath()
      ctx.fill()
      ctx.stroke()
      drew = true
    }
    if (!drew && ann.bbox.length >= 4) {
      const [bx, by, bw, bh] = ann.bbox
      ctx.fillRect(bx * sx, by * sy, bw * sx, bh * sy)
      ctx.strokeRect(bx * sx, by * sy, bw * sx, bh * sy)
    }

    if (isSelected) {
      // Second pass: bright polygon outline (not bbox) so the full shape pops.
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1.5
      ctx.globalAlpha = 0.9
      for (const ring of ann.segmentation) {
        if (ring.length < 6) continue
        ctx.beginPath()
        for (let i = 0; i + 1 < ring.length; i += 2) {
          const x = ring[i] * sx
          const y = ring[i + 1] * sy
          if (i === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.closePath()
        ctx.stroke()
      }
      // Centre crosshair ties the filled polygon back to the 3D point.
      const cx = ann.center.x * sx
      const cy = ann.center.y * sy
      ctx.strokeStyle = SELECTED
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(cx - 8, cy)
      ctx.lineTo(cx + 8, cy)
      ctx.moveTo(cx, cy - 8)
      ctx.lineTo(cx, cy + 8)
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(cx, cy, 4, 0, Math.PI * 2)
      ctx.stroke()
    }

    if (ann.label) {
      const lx = ann.center.x * sx
      const ly = Math.max(12, ann.center.y * sy - 6)
      ctx.font = '600 10px ui-monospace, SFMono-Regular, Menlo, monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      const text = ann.label.toUpperCase()
      const padX = 4
      const tw = ctx.measureText(text).width + padX * 2
      const th = 12
      ctx.fillStyle = 'rgba(10, 14, 18, 0.72)'
      ctx.fillRect(lx - tw / 2, ly - th, tw, th)
      ctx.fillStyle = color
      ctx.fillText(text, lx, ly - 2)
    }
    ctx.globalAlpha = 1
  }
}
