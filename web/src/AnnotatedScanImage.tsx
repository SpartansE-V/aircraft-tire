/** Renders a scan image with 2D overlays from metadata.json.

Display rules:
  - crack         → geometry only (no "crack" text)
  - tread-shallow → geometry + "shallow" label
  - wheel / tread → omitted by the API

Pass ``rotate={90}`` to stand a wide flatten strip upright (CW).
*/

import { useEffect, useRef, useState } from 'react'

export type ScanAnnotation2D = {
  category: 'crack' | 'tread-shallow'
  label: string | null
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

export default function AnnotatedScanImage({
  image,
  alt,
  className = '',
  rotate = 0,
  fill = false,
}: {
  image: AnnotatedScanImageData
  alt?: string
  className?: string
  /** Degrees clockwise — use 90 to stand flatten images upright. */
  rotate?: 0 | 90
  /** Stretch to parent instead of intrinsic aspect ratio (match a column height). */
  fill?: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [natural, setNatural] = useState({ w: image.width, h: image.height })

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
          drawAnnotations(ctx, image.annotations, h / srcW, w / srcH)
        } else {
          ctx.drawImage(bitmap, 0, 0, w, h)
          drawAnnotations(ctx, image.annotations, w / srcW, h / srcH)
        }
        ctx.restore()
      }
      bitmap.src = image.url
    }

    paint()
    const ro = new ResizeObserver(paint)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [image, natural, rotate])

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

function drawAnnotations(
  ctx: CanvasRenderingContext2D,
  annotations: ScanAnnotation2D[],
  sx: number,
  sy: number,
) {
  for (const ann of annotations) {
    const color = STROKE[ann.category]
    ctx.strokeStyle = color
    ctx.fillStyle = `${color}33`
    ctx.lineWidth = ann.category === 'crack' ? 2 : 1.5

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
  }
}
