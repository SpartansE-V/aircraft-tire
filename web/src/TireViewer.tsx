import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { tireTypeById, type Defect, type TireModelTypeId } from './data'
import { HUE } from './charts'

type Mode = 'solid' | 'wireframe'

// SEV_COLOR is hex: it paints vertex colours and gets an alpha appended (`${c}33`).
// SEV_INK is the themed text variant — the mark hues fall under 4.5:1 on the light surface.
const SEV_COLOR = { low: HUE.warn, med: HUE.warn, high: HUE.crit }
const SEV_INK = { low: 'var(--warn)', med: 'var(--warn)', high: 'var(--crit)' }

// The GLB ships a plain domed hub. Build a vented aircraft rim instead: white face plate
// with radial vent slots, bolt ring, dark hub bore. Sized to the tire's bore (r=0.475) and
// the old wheel's extent (y -0.41..0.32); the face is the -y (outboard) side.
// Dimensions below are the Radial's; the group is scaled to the selected type's bead/width.
function buildWheel(beadR: number, halfW: number) {
  const g = new THREE.Group()
  const HALF = 0.363 // tire half-width — the whole wheel lives inside +/- this
  const SEAT = 0.47 // bead seat: the tire's bore pinches to 0.475 here, so stay under it
  const WELL = 0.42 // barrel between the seats — the "inner shaft", deliberately narrow
  const FACE_R = 0.468 // face plate, recessed inside the flange like the real wheel
  const yLo = -HALF
  const boltH = 0.035
  const faceT = 0.05
  const faceY = yLo + boltH // face plate sits back far enough for the bolts to stay flush
  const N = 18 // vent slots, and bolts staggered between them

  const white = new THREE.MeshStandardMaterial({
    color: 0xe8e8e8,
    roughness: 0.45,
    metalness: 0.05,
    side: THREE.DoubleSide,
  })

  // Rim shell as a lathed profile (radius, axial) — one mesh for well + bead seats + flared
  // flanges. The flare is what makes it read as a real rim: the edges are much wider than the
  // barrel. Radii track the tire's own bore profile (0.475 at the seat, 0.550 at the edge),
  // so the flange fills the tire's bead hook instead of poking through it.
  const profile = [
    [0.545, -0.363], // flange tip, outboard
    [0.54, -0.348],
    [0.495, -0.318],
    [SEAT, -0.287], // bead seat
    [0.455, -0.255],
    [WELL, -0.215], // drop into the well
    [WELL, 0.215],
    [0.455, 0.255],
    [SEAT, 0.287], // bead seat
    [0.495, 0.318],
    [0.54, 0.348],
    [0.545, 0.363], // flange tip, inboard
  ].map(([r, y]) => new THREE.Vector2(r, y))
  g.add(new THREE.Mesh(new THREE.LatheGeometry(profile, 64), white))

  // Face plate: disc with a centre bore and N tapered radial slots cut through it.
  const shape = new THREE.Shape().absarc(0, 0, FACE_R, 0, Math.PI * 2, false)
  shape.holes.push(new THREE.Path().absarc(0, 0, 0.15, 0, Math.PI * 2, true))
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2
    const [r0, r1, w0, w1] = [0.2, 0.35, 0.024, 0.038] // inner/outer radius, cap radii (taper)
    const slot = new THREE.Path()
    slot.absarc(Math.cos(a) * r1, Math.sin(a) * r1, w1, a - Math.PI / 2, a + Math.PI / 2, false)
    slot.absarc(Math.cos(a) * r0, Math.sin(a) * r0, w0, a + Math.PI / 2, a + Math.PI * 1.5, false)
    slot.closePath()
    shape.holes.push(slot)
  }
  const face = new THREE.Mesh(
    new THREE.ExtrudeGeometry(shape, { depth: faceT, bevelEnabled: false, curveSegments: 24 }),
    white,
  )
  face.rotation.x = -Math.PI / 2 // shape's XY plane -> XZ, extrudes along +Y
  face.position.y = faceY
  g.add(face)

  // Bolt heads stand proud of the face plate, ending flush with the tire sidewall.
  const steel = new THREE.MeshStandardMaterial({ color: 0xb8b8b8, roughness: 0.35, metalness: 0.9 })
  const boltGeo = new THREE.CylinderGeometry(0.022, 0.024, boltH, 12)
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2 + Math.PI / N
    const bolt = new THREE.Mesh(boltGeo, steel)
    bolt.position.set(Math.cos(a) * 0.4, yLo + boltH / 2, Math.sin(a) * 0.4)
    g.add(bolt)
  }

  // Dark hub bore, recessed behind the face.
  const bore = new THREE.Mesh(
    new THREE.CylinderGeometry(0.148, 0.148, 0.17, 32),
    new THREE.MeshStandardMaterial({ color: 0x3a3228, roughness: 0.5, metalness: 0.8 }),
  )
  bore.position.y = faceY + faceT + 0.085
  g.add(bore)

  // Built around +Y, but both GLB nodes carry a +90deg X quaternion, so the tire's axle is
  // world +Z. Match it exactly, or the wheel sits crosswise to the tire.
  g.rotation.x = Math.PI / 2
  g.scale.set(beadR / 0.48, halfW / 0.363, beadR / 0.48) // lathe axis is +Y -> axial
  return g
}

// ponytail: full scene rebuild when the selected wheel changes — the GLB is 350 kB and
// browser-cached, and it's one mesh. Diff the geometry only if switching ever feels slow.
export default function TireViewer({
  defects,
  serial,
  theme,
  modelType = 'radial',
}: {
  defects: Defect[]
  serial: string
  theme: 'dark' | 'light'
  /** Construction type from the database — one GLB per wheel, no type switcher. */
  modelType?: TireModelTypeId
}) {
  const host = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<Mode>('solid')
  const [error, setError] = useState<string | null>(null)
  const setWireframe = useRef<((w: boolean) => void) | null>(null)
  const tt = tireTypeById(modelType)

  useEffect(() => {
    setError(null)
    const el = host.current!
    const scene = new THREE.Scene()

    const camera = new THREE.PerspectiveCamera(42, el.clientWidth / el.clientHeight, 0.1, 1000)
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(el.clientWidth, el.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    el.appendChild(renderer.domElement)

    // The canvas is alpha:true, so the page surface shows through: dark gets the moody cyan
    // rim light, light mode gets a neutral studio fill or the tire reads as a black blob.
    const light = theme === 'light'
    scene.add(new THREE.HemisphereLight(light ? 0xffffff : 0x9fd8ff, light ? 0xc8d2da : 0x0a1016, light ? 2.4 : 1.1))
    const key = new THREE.DirectionalLight(0xffffff, light ? 2.6 : 2.2)
    key.position.set(5, 8, 5)
    scene.add(key)
    const rim = new THREE.DirectionalLight(light ? 0xdfe8ee : 0x04a2c2, light ? 1.6 : 2.4)
    rim.position.set(-6, -1, -5)
    scene.add(rim)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.9

    let mesh: THREE.Mesh | null = null

    new GLTFLoader().load(
      tt.model,
      (gltf) => {
        const model = gltf.scene
        scene.add(model)

        // Swap the GLB's plain hub for the vented rim (before framing, so the bbox is right).
        model.getObjectByName('Wheel')?.removeFromParent()
        model.add(buildWheel(tt.beadR, tt.halfW))

        // Fit the whole tire in frame: pull back far enough for its largest dimension,
        // widened when the viewport is narrow (vertical FOV is the fixed one).
        const box = new THREE.Box3().setFromObject(model)
        const s = box.getSize(new THREE.Vector3())
        const size = Math.max(s.x, s.y, s.z)
        model.position.sub(box.getCenter(new THREE.Vector3()))
        const fit = (size / 2 / Math.tan((camera.fov * Math.PI) / 360)) * 1.45
        const dist = fit / Math.min(1, camera.aspect)
        camera.position.set(0, dist * 0.3, dist * 0.95)
        camera.near = dist / 100
        camera.far = dist * 10
        camera.updateProjectionMatrix()
        controls.minDistance = size * 0.7
        controls.maxDistance = dist * 2

        const grid = new THREE.GridHelper(size * 2.4, 24, light ? 0xb6c4cd : 0x1d3340, light ? 0xd2dbe1 : 0x14222b)
        grid.position.y = -s.y * 0.62
        scene.add(grid)

        // Crack overlays only — healthy tires arrive with defects=[] so nothing paints.
        const tire = model.getObjectByName('Tire') as THREE.Mesh | undefined
        if (!tire) return
        mesh = tire
        const base = (tire.material as THREE.MeshStandardMaterial).color.clone()
        const mat = (tire.material as THREE.MeshStandardMaterial).clone()
        mat.color.set(0xffffff)
        mat.vertexColors = true
        tire.material = mat

        const pos = tire.geometry.attributes.position
        const baseColors = new Float32Array(pos.count * 3)
        const colors = new Float32Array(pos.count * 3)
        const hitIdx = new Int16Array(pos.count)
        const v = new THREE.Vector3()
        const tint = new THREE.Color()
        hitIdx.fill(-1)
        for (let i = 0; i < pos.count; i++) {
          v.fromBufferAttribute(pos, i)
          let best = -1
          let bestDist = Infinity
          for (let di = 0; di < defects.length; di++) {
            const d = defects[di]
            const dist = v.distanceTo(new THREE.Vector3(...d.at))
            if (dist < d.r && dist < bestDist) {
              bestDist = dist
              best = di
            }
          }
          hitIdx[i] = best
          ;(best >= 0 ? tint.set(SEV_COLOR[defects[best].severity]) : base).toArray(baseColors, i * 3)
        }
        colors.set(baseColors)
        tire.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))

        setWireframe.current = (w) => {
          mat.wireframe = w
        }
        setWireframe.current(mode === 'wireframe')

        // Wave pulse: expand/contract crack highlight radius via vertex colour intensity.
        const waveClock = new THREE.Clock()
        const paintWave = () => {
          if (!defects.some((d) => d.wave !== false && d.kind === 'damage')) return
          const t = waveClock.getElapsedTime()
          const pulse = 0.55 + 0.45 * Math.sin(t * 3.2)
          const warm = new THREE.Color()
          for (let i = 0; i < pos.count; i++) {
            const di = hitIdx[i]
            if (di < 0) {
              colors[i * 3] = baseColors[i * 3]
              colors[i * 3 + 1] = baseColors[i * 3 + 1]
              colors[i * 3 + 2] = baseColors[i * 3 + 2]
              continue
            }
            const d = defects[di]
            if (d.wave === false) continue
            warm.set(SEV_COLOR[d.severity])
            warm.lerp(base, 1 - pulse)
            warm.toArray(colors, i * 3)
          }
          const attr = tire.geometry.getAttribute('color') as THREE.BufferAttribute
          attr.needsUpdate = true
        }
        ;(tire as THREE.Mesh & { __paintWave?: () => void }).__paintWave = paintWave
      },
      undefined,
      () => setError(`${tt.model} failed to load`),
    )

    // Defect callouts: project the zone centres to screen space each frame and drive the
    // HTML markers directly (no React re-render in the animation loop).
    const p = new THREE.Vector3()
    const cam = new THREE.Vector3()
    const tick = () => {
      controls.update()
      const paintWave = (mesh as (THREE.Mesh & { __paintWave?: () => void }) | null)?.__paintWave
      paintWave?.()
      renderer.render(scene, camera)
      if (mesh && overlay.current) {
        camera.getWorldPosition(cam)
        const kids = overlay.current.children as HTMLCollectionOf<HTMLElement>
        defects.forEach((d, i) => {
          const node = kids[i]
          if (!node) return
          p.set(...d.at)
          mesh!.localToWorld(p)
          const facing = p.dot(cam) > 0
          p.project(camera)
          node.style.transform = `translate(-50%,-50%) translate(${((p.x + 1) / 2) * el.clientWidth}px, ${((1 - p.y) / 2) * el.clientHeight}px)`
          node.style.opacity = facing ? '1' : '0.2'
        })
      }
      raf = requestAnimationFrame(tick)
    }
    let raf = requestAnimationFrame(tick)

    const onResize = () => {
      camera.aspect = el.clientWidth / el.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(el.clientWidth, el.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      renderer.dispose()
      el.removeChild(renderer.domElement)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defects, theme, modelType])

  useEffect(() => setWireframe.current?.(mode === 'wireframe'), [mode])

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={host} className="h-full w-full" />

      {/* projected defect callouts — crack centres drive the wave highlight */}
      <div ref={overlay} className="pointer-events-none absolute inset-0">
        {defects.map((d) => (
          <div key={d.label} className="absolute left-0 top-0 flex items-center gap-2 whitespace-nowrap">
            <span
              className={`h-2.5 w-2.5 rotate-45 border ${d.wave !== false ? 'animate-pulse' : ''}`}
              style={{ borderColor: SEV_COLOR[d.severity], background: `${SEV_COLOR[d.severity]}33` }}
            />
            <span
              className="border-l pl-2 text-[10px] uppercase tracking-widest"
              style={{ borderColor: SEV_COLOR[d.severity], color: SEV_INK[d.severity] }}
            >
              {d.kind === 'damage' ? '⚠ ' : '≈ '}
              {d.zone}
              {d.lateral_pct != null && (
                <span className="ml-1 text-[var(--ink-4)]">· {d.lateral_pct > 0 ? '+' : ''}{d.lateral_pct.toFixed(0)}%</span>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="pointer-events-none absolute inset-0 scanline" />
      <Corners />

      <div className="absolute left-4 top-4 flex text-[11px] uppercase tracking-widest">
        {(['solid', 'wireframe'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`border border-[var(--line-2)] px-3 py-1.5 transition-colors first:border-r-0 ${
              mode === m ? 'bg-[var(--primary-soft)] text-[var(--primary)]' : 'text-[var(--ink-3)] hover:text-[var(--ink-2)]'
            }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Construction type is fixed per wheel from the database — display only. */}
      <div className="absolute right-4 top-4 w-52 text-right">
        <div className="inline-block border border-[var(--line-2)] bg-[var(--primary-soft)] px-2.5 py-1.5 text-[11px] uppercase tracking-widest text-[var(--primary)]">
          {tt.name}
        </div>
        <p className="mt-2 text-[10px] uppercase tracking-widest text-[var(--ink-3)]">
          {tt.fits}
          <span className="ml-1.5 text-[var(--primary)]">· fitted</span>
        </p>
        <p className="mt-1 text-[10px] leading-relaxed text-[var(--ink-4)]">{tt.planes}</p>
        <p className="mt-1 text-[10px] leading-relaxed text-[var(--ink-4)]">{tt.note}</p>
      </div>

      <div className="absolute bottom-4 left-4 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
        3D laser scan · {serial} · {tt.name} · orbit / scroll to inspect
      </div>

      {error && <p className="absolute inset-0 flex items-center justify-center text-sm text-[var(--crit)]">{error}</p>}
    </div>
  )
}

function Corners() {
  const c = 'pointer-events-none absolute h-4 w-4 border-[var(--primary-dim)]'
  return (
    <>
      <span className={`${c} left-2 top-2 border-l border-t`} />
      <span className={`${c} right-2 top-2 border-r border-t`} />
      <span className={`${c} bottom-2 left-2 border-b border-l`} />
      <span className={`${c} bottom-2 right-2 border-b border-r`} />
    </>
  )
}
