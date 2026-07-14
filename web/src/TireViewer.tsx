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
/** Selected crack — cyan so it reads apart from severity reds on both 2D and 3D. */
const SELECTED_COLOR = 0x22d3ee
const SELECTED_HEX = '#22d3ee'

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

/**
 * What the runway is doing to this tyre, right now.
 *
 * `contactDeg` is where the tarmac is touching it, around its own tread. `peakDeg` is where it was
 * touching at the instant the tyre was hit hardest — the arc that actually took the landing. Both are
 * drawn in blue, which is the one hue the tyre does not already use: black rubber, amber wear, red
 * damage. Blue is the runway.
 */
export type Impact = {
  contactDeg: number
  arcDeg: number
  loadKN: number
  peakLoadKN: number
  peakDeg: number
  peakArcDeg: number
  slipMps: number
  contact: boolean
  /** The flat spot, if the wheel locked. Ground into one arc, and it does not come out. */
  flatMm: number
  flatDeg: number
}

const IMPACT_HUE = 0x35c8f0
const FLAT_HUE = 0xff4d4d // the flat spot is damage, not contact — it gets the damage colour

/**
 * A band of tread, drawn as an open cylinder arc: an arc about the tyre's axle IS a strip of tread.
 * `arcDeg` is how much of the circumference it covers, and that is not decoration — a harder-loaded
 * tyre squashes flatter and touches the runway along a longer patch.
 *
 * The band goes on as a child of the tyre mesh, so it works in that mesh's *local* frame — where the
 * axle is +Y (the bounding box is 2 × 0.826 × 2; the odd dimension is the width). A CylinderGeometry
 * is already built around +Y, so it needs no rotation at all. The mesh's own 90° quaternion is what
 * swings the whole thing to lie on its side in the scene, and the band comes along for the ride.
 */
function treadBand(radius: number, width: number, arcDeg: number, opacity: number, color = IMPACT_HUE, additive = true) {
  const geo = new THREE.CylinderGeometry(radius, radius, width, 48, 1, true, 0, (arcDeg * Math.PI) / 180)
  return new THREE.Mesh(
    geo,
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
      ...(additive ? { blending: THREE.AdditiveBlending } : {}),
    }),
  )
}

/** Radius and width of the tread, from the mesh's own geometry — the axle is the odd axis out. */
function treadSize(geo: THREE.BufferGeometry) {
  geo.computeBoundingBox()
  const b = geo.boundingBox!.getSize(new THREE.Vector3())
  return { radius: Math.max(b.x, b.z) / 2, width: b.y }
}

// ponytail: full scene rebuild when the selected wheel changes — the GLB is 350 kB and
// browser-cached, and it's one mesh. Diff the geometry only if switching ever feels slow.
export default function TireViewer({
  defects,
  serial,
  theme,
  impact,
  compact = false,
  modelType = 'radial',
  selectedLabel = null,
  onSelectCrack,
}: {
  defects: Defect[]
  serial: string
  theme: 'dark' | 'light'
  impact?: Impact
  /** The landing page gives this a narrow column, where the type badge and its notes are wider than
   *  the panel and land on top of everything else. There, the tyre and the impact are the whole point. */
  compact?: boolean
  /** Construction type from the database — one GLB per wheel, no type switcher. */
  modelType?: TireModelTypeId
  /** Defect.label of the crack highlighted on both 2D and 3D views. */
  selectedLabel?: string | null
  onSelectCrack?: (label: string | null) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<Mode>('solid')
  const [error, setError] = useState<string | null>(null)
  const setWireframe = useRef<((w: boolean) => void) | null>(null)
  const tt = tireTypeById(modelType)

  // The impact changes every frame of the landing; the scene must not be torn down for that. Hand it
  // to the render loop through a ref instead of putting it in the effect's dependencies.
  const impactRef = useRef(impact)
  impactRef.current = impact
  const selectedRef = useRef(selectedLabel)
  selectedRef.current = selectedLabel
  const onSelectRef = useRef(onSelectCrack)
  onSelectRef.current = onSelectCrack

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
    let live: THREE.Mesh | null = null
    let peak: THREE.Mesh | null = null
    let flat: THREE.Mesh | null = null
    // Pulsing point marker at the selected crack centre (2D polygon ↔ this point).
    const selectPoint = new THREE.Mesh(
      new THREE.SphereGeometry(0.045, 20, 16),
      new THREE.MeshBasicMaterial({
        color: SELECTED_COLOR,
        transparent: true,
        opacity: 0.95,
        depthTest: false,
      }),
    )
    selectPoint.visible = false
    selectPoint.renderOrder = 10
    const selectHalo = new THREE.Mesh(
      new THREE.SphereGeometry(0.09, 20, 16),
      new THREE.MeshBasicMaterial({
        color: SELECTED_COLOR,
        transparent: true,
        opacity: 0.28,
        depthTest: false,
        depthWrite: false,
      }),
    )
    selectHalo.visible = false
    selectHalo.renderOrder = 9
    const selectGroup = new THREE.Group()
    selectGroup.add(selectHalo, selectPoint)
    selectGroup.visible = false

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

        // The runway, on the tyre. Sized off the model's own tread rather than guessed units, so it
        // still lands on the rubber if the tyre type is swapped.
        const { radius, width } = treadSize(tire.geometry)
        peak = treadBand(radius * 1.005, width * 0.98, 1, 0.45) // the arc that took the hit
        live = treadBand(radius * 1.02, width * 0.86, 1, 0.9) // where the tarmac is touching right now
        // The flat spot is not contact, it is damage — so it gets the damage colour and sits flush on
        // the tread rather than glowing above it. Rubber that is no longer there.
        flat = treadBand(radius * 1.001, width * 0.99, 1, 0.95, FLAT_HUE, false)
        tire.add(peak, live, flat, selectGroup)

        setWireframe.current = (w) => {
          mat.wireframe = w
        }
        setWireframe.current(mode === 'wireframe')

        // Wave pulse: expand/contract crack highlight radius via vertex colour intensity.
        // Selected crack: cyan point marker + local tint; peers dim so the 2D polygon link is clear.
        const waveClock = new THREE.Clock()
        const paintWave = () => {
          const t = waveClock.getElapsedTime()
          const pulse = 0.55 + 0.45 * Math.sin(t * 3.2)
          const selected = selectedRef.current
          const warm = new THREE.Color()

          // Drive the 3D selection point from the shared label (set by 2D polygon click too).
          const sel = selected ? defects.find((d) => d.label === selected) : undefined
          if (sel) {
            selectGroup.visible = true
            selectPoint.visible = true
            selectHalo.visible = true
            selectGroup.position.set(...sel.at)
            const s = 0.85 + 0.35 * pulse
            selectPoint.scale.setScalar(s)
            selectHalo.scale.setScalar(0.9 + 0.55 * pulse)
            ;(selectPoint.material as THREE.MeshBasicMaterial).opacity = 0.75 + 0.25 * pulse
            controls.autoRotate = false
          } else {
            selectGroup.visible = false
            controls.autoRotate = true
          }

          if (!defects.some((d) => d.wave !== false && d.kind === 'damage')) return

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
            const isSelected = selected != null && d.label === selected
            const dimOthers = selected != null && !isSelected
            if (isSelected) {
              // Soft local tint around the point — the sphere is the primary "point" cue.
              warm.setHex(SELECTED_COLOR)
              warm.lerp(base, 0.35 + 0.25 * (1 - pulse))
            } else if (dimOthers) {
              warm.set(SEV_COLOR[d.severity])
              warm.lerp(base, 0.88)
            } else {
              warm.set(SEV_COLOR[d.severity])
              warm.lerp(base, 1 - pulse)
            }
            warm.toArray(colors, i * 3)
          }
          const attr = tire.geometry.getAttribute('color') as THREE.BufferAttribute
          attr.needsUpdate = true
        }
        ;(tire as THREE.Mesh & { __paintWave?: () => void; __hitIdx?: Int16Array }).__paintWave = paintWave
        ;(tire as THREE.Mesh & { __hitIdx?: Int16Array }).__hitIdx = hitIdx
      },
      undefined,
      () => setError(`${tt.model} failed to load`),
    )

    // Click a crack on the mesh (or empty rubber) to sync selection with 2D overlays.
    // Ignore drags so orbiting the tyre does not clear the selection.
    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let downX = 0
    let downY = 0
    const onPointerDown = (e: PointerEvent) => {
      downX = e.clientX
      downY = e.clientY
    }
    const onCanvasClick = (e: MouseEvent) => {
      if (!onSelectRef.current || !mesh) return
      if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const hits = raycaster.intersectObject(mesh, false)
      if (!hits.length) {
        onSelectRef.current(null)
        return
      }
      // Prefer the defect whose centre is closest to the hit (within its paint radius).
      const pt = hits[0].point.clone()
      mesh.worldToLocal(pt)
      let bestDi = -1
      let bestDist = Infinity
      for (let di = 0; di < defects.length; di++) {
        const d = defects[di]
        const dist = pt.distanceTo(new THREE.Vector3(...d.at))
        if (dist < d.r * 1.35 && dist < bestDist) {
          bestDist = dist
          bestDi = di
        }
      }
      if (bestDi < 0) {
        // Fallback: vertex colour map (same radii used when painting).
        const face = hits[0].face
        const hitIdx = (mesh as THREE.Mesh & { __hitIdx?: Int16Array }).__hitIdx
        if (face && hitIdx) {
          const posAttr = mesh.geometry.attributes.position
          const tmp = new THREE.Vector3()
          for (const vi of [face.a, face.b, face.c]) {
            tmp.fromBufferAttribute(posAttr, vi)
            const di = hitIdx[vi]
            if (di < 0) continue
            const dist = tmp.distanceToSquared(pt)
            if (dist < bestDist) {
              bestDist = dist
              bestDi = di
            }
          }
        }
      }
      const label = bestDi >= 0 ? defects[bestDi].label : null
      onSelectRef.current(label === selectedRef.current ? null : label)
    }
    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    renderer.domElement.addEventListener('click', onCanvasClick)

    // Defect callouts: project the zone centres to screen space each frame and drive the
    // HTML markers directly (no React re-render in the animation loop).
    const p = new THREE.Vector3()
    const cam = new THREE.Vector3()
    // Rebuilding an arc's geometry 60 times a second would be silly. The band is built once as a full
    // ring's worth of arc and then *rotated* into place, with its arc length set by rebuilding only
    // when the width actually changes — which is when the load changes, not every frame.
    let liveArc = -1
    let peakArc = -1
    let flatArc = -1
    const setArc = (m: THREE.Mesh, r: number, w: number, deg: number) => {
      m.geometry.dispose()
      m.geometry = new THREE.CylinderGeometry(r, r, w, 48, 1, true, 0, (Math.max(2, deg) * Math.PI) / 180)
    }

    const tick = () => {
      controls.update()

      const im = impactRef.current
      if (live && peak && flat && mesh) {
        const on = !!im && im.contact && im.loadKN > 1
        live.visible = on
        peak.visible = !!im && im.peakLoadKN > 1
        flat.visible = !!im && im.flatMm > 0.1
        if (im && mesh) {
          const { radius, width } = treadSize(mesh.geometry)
          if (Math.abs(im.arcDeg - liveArc) > 0.5) {
            setArc(live, radius * 1.02, width * 0.86, im.arcDeg)
            liveArc = im.arcDeg
          }
          if (Math.abs(im.peakArcDeg - peakArc) > 0.5) {
            setArc(peak, radius * 1.005, width * 0.98, im.peakArcDeg)
            peakArc = im.peakArcDeg
          }
          // The flat is the contact patch, ground in place — it is as wide as the patch that made it.
          if (Math.abs(im.peakArcDeg - flatArc) > 0.5) {
            setArc(flat, radius * 1.001, width * 0.99, im.peakArcDeg)
            flatArc = im.peakArcDeg
          }
          flat.rotation.y = ((im.flatDeg - im.peakArcDeg / 2) * Math.PI) / 180
          // A cylinder arc starts at its own 0 and runs anticlockwise, so centre it on the angle.
          live.rotation.y = ((im.contactDeg - im.arcDeg / 2) * Math.PI) / 180
          peak.rotation.y = ((im.peakDeg - im.peakArcDeg / 2) * Math.PI) / 180
          // Brighter the harder it is being pressed. Sliding tread glows: that is the abrasion.
          const load = Math.min(1, im.loadKN / Math.max(im.peakLoadKN, 1))
          const slip = Math.min(1, im.slipMps / 30)
          ;(live.material as THREE.MeshBasicMaterial).opacity = 0.35 + 0.45 * load + 0.25 * slip
        }
      }

      const paintWave = (mesh as (THREE.Mesh & { __paintWave?: () => void }) | null)?.__paintWave
      paintWave?.()
      renderer.render(scene, camera)
      if (mesh && overlay.current) {
        camera.getWorldPosition(cam)
        const kids = overlay.current.children as HTMLCollectionOf<HTMLElement>
        const selected = selectedRef.current
        defects.forEach((d, i) => {
          const node = kids[i]
          if (!node) return
          p.set(...d.at)
          mesh!.localToWorld(p)
          const facing = p.dot(cam) > 0
          p.project(camera)
          node.style.transform = `translate(-50%,-50%) translate(${((p.x + 1) / 2) * el.clientWidth}px, ${((1 - p.y) / 2) * el.clientHeight}px)`
          const isSelected = selected != null && d.label === selected
          const dimOthers = selected != null && !isSelected
          if (isSelected) node.style.opacity = '1'
          else if (dimOthers) node.style.opacity = facing ? '0.22' : '0.08'
          else node.style.opacity = facing ? '1' : '0.2'
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
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('click', onCanvasClick)
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
        {defects.map((d) => {
          const isSelected = selectedLabel != null && d.label === selectedLabel
          const dimOthers = selectedLabel != null && !isSelected
          const mark = isSelected ? SELECTED_HEX : SEV_COLOR[d.severity]
          const ink = isSelected ? SELECTED_HEX : SEV_INK[d.severity]
          return (
            <div
              key={d.label}
              className={`absolute left-0 top-0 flex items-center gap-2 whitespace-nowrap transition-opacity ${
                onSelectCrack ? 'pointer-events-auto cursor-pointer' : ''
              } ${dimOthers ? 'opacity-30' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onSelectCrack?.(isSelected ? null : d.label)
              }}
            >
              <span
                className={`rotate-45 border ${isSelected ? 'h-3.5 w-3.5' : 'h-2.5 w-2.5'} ${
                  d.wave !== false || isSelected ? 'animate-pulse' : ''
                }`}
                style={{ borderColor: mark, background: `${mark}33`, boxShadow: isSelected ? `0 0 10px ${mark}` : undefined }}
              />
              <span
                className={`border-l pl-2 uppercase tracking-widest ${isSelected ? 'text-[11px] font-semibold' : 'text-[10px]'}`}
                style={{ borderColor: mark, color: ink }}
              >
                {d.kind === 'damage' ? '⚠ ' : '≈ '}
                {d.zone}
                {d.source && (
                  <span className="ml-1 text-[var(--ink-4)]">· {d.source}</span>
                )}
                {d.lateral_pct != null && (
                  <span className="ml-1 text-[var(--ink-4)]">· {d.lateral_pct > 0 ? '+' : ''}{d.lateral_pct.toFixed(0)}%</span>
                )}
              </span>
            </div>
          )
        })}
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
      <div className={`absolute right-4 top-4 w-52 text-right ${compact ? 'hidden' : ''}`}>
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

      {/* The runway, on this tyre. Blue is the one hue the tyre does not already use — black rubber,
          amber wear, red damage — so an impact can never be confused for a defect. */}
      {impact && impact.peakLoadKN > 1 && (
        <div className="absolute bottom-3 right-3 border-l bg-[var(--panel)]/85 py-1 pl-2 text-right text-[10px] uppercase tracking-widest" style={{ borderColor: `#${IMPACT_HUE.toString(16)}` }}>
          <div style={{ color: `#${IMPACT_HUE.toString(16)}` }}>■ Runway contact</div>
          <div className="mt-1 text-[var(--ink-3)]">
            Hit {Math.round(impact.peakDeg)}° · {Math.round(impact.peakArcDeg)}° of tread · {Math.round(impact.peakLoadKN)} kN
          </div>
          <div className="mt-0.5 text-[var(--ink-4)]">
            {impact.contact
              ? `Now ${Math.round(impact.contactDeg)}° · ${impact.slipMps > 0.5 ? `sliding ${impact.slipMps.toFixed(0)} m/s` : 'rolling'}`
              : 'Off the runway'}
          </div>
          {impact.flatMm > 0.1 && (
            <div className="mt-1 border-t pt-1" style={{ borderColor: `#${FLAT_HUE.toString(16)}` }}>
              <span style={{ color: `#${FLAT_HUE.toString(16)}` }}>■ Flat spot {impact.flatMm.toFixed(1)} mm</span>
              <div className="mt-0.5 text-[var(--ink-4)]">Wheel locked at {Math.round(impact.flatDeg)}° and ground there</div>
            </div>
          )}
        </div>
      )}

      <div className={`absolute bottom-4 left-4 text-[10px] uppercase tracking-widest text-[var(--ink-4)] ${compact ? 'hidden' : ''}`}>
        3D laser scan · {serial} · {tt.name} · orbit / scroll
        {onSelectCrack ? ' · click crack (circle or flatten) to link 2D↔3D' : ' to inspect'}
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
