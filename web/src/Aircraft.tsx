import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { HUE } from './charts'
import { FLEET_TIRES, statusOf } from './data'
import type { Attitude, LandingFrame } from './landingEngine'
import { useMock } from './mock'
import { active, ENV, type Track } from './tracks'
import type { Theme } from './ui'

// Boeing 777-300ER (b777.glb). The model is metric, +z forward, +y up, and its origin sits on the
// ground between the main bogies — so rotating it about y=π/2 puts the nose at +x (our convention)
// and attitude rotations already pivot at the main-gear contact point, which is where the physics
// pivots. Nothing about the airframe is authored here; the only thing we add is the tire mapping.

const STATUS_HUE = { ok: HUE.ok, watch: HUE.warn, action: HUE.crit }
// A wheel with no telemetry behind it. The wheel is real; the verdict about it was invented, so with
// mock off the pip goes grey rather than green — an unlit lamp, not a passing one.
const NO_FEED_HUE = '#5f6f7d'
const ZERO = new THREE.Vector3()

export type CamPreset = 'field' | 'chase' | 'side' | 'gear'

/**
 * Camera presets, derived from the airframe once it has loaded rather than hard-coded in metres —
 * swap the GLB for a different aircraft and the framing still works.
 * `len` is the fuselage length; `bogie` is the centre of the left main gear.
 */
function camPresets(len: number, bogie: THREE.Vector3): Record<CamPreset, [THREE.Vector3, THREE.Vector3]> {
  return {
    // FIELD is replaced per-airport by buildAirport, which knows the real extents. This is only the
    // placeholder for the moment before the first airport exists.
    field: [new THREE.Vector3(-1600, 1500, 2100), new THREE.Vector3(900, 0, 0)],
    chase: [new THREE.Vector3(-len * 1.5, len * 0.38, len * 0.85), new THREE.Vector3(-len * 0.1, len * 0.06, 0)],
    side: [new THREE.Vector3(0, len * 0.14, len * 1.75), new THREE.Vector3(0, len * 0.07, 0)],
    // Aft-outboard of the left bogie: the wheels are the subject, the airframe is the backdrop.
    gear: [
      bogie.clone().add(new THREE.Vector3(-len * 0.13, len * 0.05, -len * 0.14)),
      bogie.clone().add(new THREE.Vector3(0, -len * 0.005, 0)),
    ],
  }
}

/**
 * Find the wheels in the airframe and name them.
 *
 * The GLB's node names are Sketchfab noise (`Group_048_<Black>_0`), so identity comes from the only
 * thing that is actually reliable: the black rubber material, and where the wheel sits. Sorting by
 * position and dealing out FLEET_TIRES' ids in the same order (nose L/R, then per bogie fwd→aft,
 * outer→inner) means the tire you click is the tire you read. If the model ever changes, the ids
 * follow it — nothing here is a hard-coded coordinate.
 */
function mapWheels(root: THREE.Object3D) {
  const found: { mesh: THREE.Mesh; c: THREE.Vector3; r: number }[] = []
  root.updateWorldMatrix(true, true)
  root.traverse((o) => {
    const m = o as THREE.Mesh
    if (!m.isMesh) return
    const mats = Array.isArray(m.material) ? m.material : [m.material]
    if (!mats.some((mm) => /black/i.test(mm.name))) return // the tires, and only the tires
    m.geometry.computeBoundingSphere()
    const bs = m.geometry.boundingSphere!
    // The GLB carries node scaling, so the geometry's own radius is not metres. Scale it into world.
    const s = new THREE.Vector3().setFromMatrixScale(m.matrixWorld)
    found.push({ mesh: m, c: bs.center.clone().applyMatrix4(m.matrixWorld), r: bs.radius * Math.max(s.x, s.y, s.z) })
  })

  // Nose gear is the pair furthest forward; everything else is a main.
  const byX = [...found].sort((a, b) => b.c.x - a.c.x)
  const nose = byX.slice(0, 2).sort((a, b) => a.c.z - b.c.z) // -z is the left side
  const mains = byX.slice(2)

  const out: { id: string; mesh: THREE.Mesh; c: THREE.Vector3; r: number }[] = []
  const noseTires = FLEET_TIRES.filter((t) => t.gear === 'nose')
  nose.forEach((w, i) => out.push({ id: noseTires[i].id, ...w }))

  // Don't assume the fleet numbers both bogies the same way round — it doesn't (the left is numbered
  // outer-first, the right inner-first). Read each wheel's axle/side/role off the geometry and let
  // data.ts say which tire that is. The data is the source of truth; the model just has to match it.
  const AXLES = ['Fwd', 'Mid', 'Aft'] as const
  for (const gear of ['left', 'right'] as const) {
    const bogie = mains.filter((w) => (gear === 'left' ? w.c.z < 0 : w.c.z > 0))
    const axleX = [...new Set(bogie.map((w) => +w.c.x.toFixed(2)))].sort((a, b) => b - a) // fwd -> aft
    const outerZ = Math.max(...bogie.map((w) => Math.abs(w.c.z)))
    for (const w of bogie) {
      const axle = AXLES[axleX.indexOf(+w.c.x.toFixed(2))]
      const role = Math.abs(Math.abs(w.c.z) - outerZ) < 0.1 ? 'outer' : 'inner'
      const tire = FLEET_TIRES.find((t) => t.gear === gear && t.role === role && t.label.includes(axle))
      if (!tire) {
        console.warn(`b777.glb: no tire in FLEET_TIRES for ${gear} ${axle} ${role}`)
        continue
      }
      out.push({ id: tire.id, ...w })
    }
  }
  return out
}

export default function Aircraft({
  selected,
  onSelect,
  attitude,
  frame,
  track,
  theme,
}: {
  selected: string
  onSelect: (id: string) => void
  attitude: Attitude
  frame?: LandingFrame
  track: Track
  theme: Theme
}) {
  const host = useRef<HTMLDivElement>(null)
  const [cam, setCam] = useState<CamPreset>('gear')
  const [hover, setHover] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const mockAllowed = useMock()
  const mockRef = useRef(mockAllowed)

  const api = useRef<{
    setAttitude: (a: Attitude) => void
    setFrame: (f: LandingFrame | undefined) => void
    setSelected: (id: string) => void
    setHover: (id: string | null) => void
    setCam: (p: CamPreset) => void
    setEnv: (t: Track, th: Theme) => void
    repaint: () => void
  }>(null)

  // The scene is built once and mutated through `api`, so a React re-render does not repaint the pips.
  useEffect(() => {
    mockRef.current = mockAllowed
    api.current?.repaint()
  }, [mockAllowed])

  useEffect(() => {
    const el = host.current!
    const scene = new THREE.Scene()
    // near = 3, not 0.1. Depth precision is spent almost entirely on the near plane, and at 0.1 there
    // was none left at runway distance — the runway and the ground fought over it and the surface
    // crawled while you orbited. OrbitControls' minDistance is 5, so nothing ever gets closer anyway.
    const camera = new THREE.PerspectiveCamera(38, 1, 3, 30000)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    renderer.domElement.style.display = 'block'
    el.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.maxPolarAngle = Math.PI / 2 - 0.02 // never orbit under the runway
    controls.minDistance = 5
    controls.maxDistance = 6000 // buildAirport raises this to fit whichever aerodrome is loaded

    const hemi = new THREE.HemisphereLight(0xdfe8f0, 0x2a3038, 1.9)
    scene.add(hemi)
    const sun = new THREE.DirectionalLight(0xffffff, 2.4)
    scene.add(sun)

    // Sky: one inside-out sphere with a vertical gradient baked into a canvas. A sphere's UVs run
    // pole to pole, so the gradient lands the right way up for free — no shader, no HDRI to fetch.
    const skyCanvas = document.createElement('canvas')
    skyCanvas.width = 1
    skyCanvas.height = 256
    const skyTex = new THREE.CanvasTexture(skyCanvas)
    const sky = new THREE.Mesh(
      new THREE.SphereGeometry(12000, 32, 20),
      new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide, fog: false, depthWrite: false }),
    )
    scene.add(sky)

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(40000, 40000), new THREE.MeshStandardMaterial({ roughness: 1 }))
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.35 // a real runway sits proud of the dirt; this also keeps them apart in z
    scene.add(ground)

    // The airport: every runway it actually has, at its true length, width, heading and offset. The
    // active one is rebuilt into the world so that landing runs along +x with the threshold at the
    // origin, which is where the aircraft and the physics already live.
    const runwayMat = new THREE.MeshStandardMaterial({
      map: runwayTexture(renderer.capabilities.getMaxAnisotropy()),
      roughness: 0.95,
      // Belt and braces against the crawl: bias the tarmac toward the camera in the depth buffer so
      // it always wins against the ground, whatever the angle.
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    })
    let fogBase: [number, number] = [400, 3000] // the env's ground-level haze, before the zoom stretch
    const apron = new THREE.Group() // holds every runway; rebuilt when the track changes
    scene.add(apron)

    const buildAirport = (tk: Track) => {
      // Group.clear() only detaches — it frees nothing. Each strip owns a geometry, so rebuilding on
      // every track switch without disposing leaks one per runway, for the life of the page.
      for (const child of apron.children) (child as THREE.Mesh).geometry.dispose()
      apron.clear()

      const a = active(tk)
      const h = (a.headingDeg * Math.PI) / 180
      // Airport frame (east, north) -> world (along-runway, lateral), with the threshold at the origin.
      const toWorld = (e: number, n: number) => {
        const de = e - a.thrE
        const dn = n - a.thrN
        return {
          x: de * Math.sin(h) + dn * Math.cos(h), // along the landing direction
          z: de * Math.cos(h) - dn * Math.sin(h), // +z is the aircraft's right
        }
      }

      const bounds = new THREE.Box3()
      a.airport.runways.forEach((r, i) => {
        const le = toWorld(r.leE, r.leN)
        const he = toWorld(r.heE, r.heN)
        bounds.expandByPoint(new THREE.Vector3(le.x, 0, le.z))
        bounds.expandByPoint(new THREE.Vector3(he.x, 0, he.z))
        const mid = { x: (le.x + he.x) / 2, z: (le.z + he.z) / 2 }

        const geo = new THREE.PlaneGeometry(r.lengthM, r.widthM)
        // Tile the markings along the strip by scaling its UVs, not by cloning the texture per runway.
        // One shared texture and one shared material for the whole airport; only geometry is per-strip.
        const uv = geo.attributes.uv as THREE.BufferAttribute
        for (let k = 0; k < uv.count; k++) uv.setX(k, uv.getX(k) * (r.lengthM / 50))
        uv.needsUpdate = true

        const strip = new THREE.Mesh(geo, runwayMat)
        strip.rotation.x = -Math.PI / 2
        // Turn each strip to its own bearing, relative to the one we are landing on.
        strip.rotation.z = -Math.atan2(he.z - le.z, he.x - le.x)
        // Runways cross. Coplanar tarmac z-fights where they overlap (JFK's 13R/31L over the 04s), so
        // give every strip its own height — a few centimetres, invisible at any real viewing distance
        // but far more than the depth buffer can confuse — with the one being landed on on top.
        const isActive = r.le === tk.rwy || r.he === tk.rwy
        strip.position.set(mid.x, isActive ? 0.15 : 0.02 + i * 0.02, mid.z)
        apron.add(strip)
      })

      // Frame the whole aerodrome from its real extents, so every airport is legible whatever its
      // shape — JFK's crossing pair and Denver's six parallels need very different framing.
      const centre = bounds.getCenter(new THREE.Vector3())
      const span = Math.max(bounds.getSize(new THREE.Vector3()).x, bounds.getSize(new THREE.Vector3()).z, 2000)
      // Stand off far enough that the whole span fits the 38° vertical FOV: half a span needs
      // ~1.45 spans of distance, and these offsets give ~1.6. Closer, and the field gets cropped.
      const eye = new THREE.Vector3(-span * 0.8, span * 1.1, span * 0.8)
      CAM.field = [centre.clone().add(eye), centre]
      // The zoom cap has to clear that, or OrbitControls quietly hauls the camera back in and the
      // field view is a crop no matter what the preset asks for. JFK spans 5.2 km and needs 8.2.
      controls.maxDistance = Math.max(600, eye.length() * 1.3)
    }

    const plane = new THREE.Group()
    plane.rotation.order = 'YZX' // yaw, then pitch, then roll
    scene.add(plane)

    // Selection ring: `depthTest: false` on purpose — the wing sits over the gear, and at whole-
    // aircraft framing a wheel is ~12 px. Anything that respects depth gets swallowed.
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(1, 0.05, 8, 36),
      new THREE.MeshBasicMaterial({ color: HUE.primary, depthTest: false, transparent: true }),
    )
    ring.renderOrder = 999
    ring.visible = false // TorusGeometry already lies in XY with a +z normal — the wheel's own plane
    plane.add(ring)

    // `rest` is where the wheel mesh sits in its own parent's frame with the gear as the model was
    // authored (parked). The strut squat is applied as an offset from it, so it never accumulates.
    type Wheel = ReturnType<typeof mapWheels>[number] & { local: THREE.Vector3; rest: THREE.Vector3 }
    let wheels: Wheel[] = []
    const unsprung: { mesh: THREE.Mesh; rest: THREE.Vector3 }[] = []
    let pickable: THREE.Mesh[] = []
    const selectedRef = { current: selected }
    const camRef = { current: cam } // the preset the user picked while the airframe was still loading

    // Status pips: the model's tires are black rubber and must stay that way to read as rubber, so
    // status rides on a ring bolted to each wheel instead of tinting it.
    const pips = new Map<string, THREE.Mesh>()

    const paint = (sel: string, hov: string | null) => {
      for (const w of wheels) {
        const pip = pips.get(w.id)
        if (!pip) continue
        const c = mockRef.current ? STATUS_HUE[statusOf(FLEET_TIRES.find((t) => t.id === w.id)!)] : NO_FEED_HUE
        const mat = pip.material as THREE.MeshBasicMaterial
        mat.color.set(c)
        mat.opacity = w.id === sel ? 1 : w.id === hov ? 0.95 : 0.75
      }
      const w = wheels.find((x) => x.id === sel)
      if (w) {
        ring.visible = true
        ring.position.copy(w.local)
        ring.scale.setScalar(w.r * 1.35)
      }
    }

    new GLTFLoader().load('/b777.glb', (gltf) => {
      const model = gltf.scene
      model.rotation.y = Math.PI / 2 // model is +z forward; our world is +x forward
      plane.add(model)

      // `local` is what everything downstream uses (pips, the selection ring, the tire-clearance
      // raise): world positions carry wherever the aircraft currently is on the approach, which is
      // not a property of the airframe.
      wheels = mapWheels(model).map((w) => ({
        ...w,
        local: plane.worldToLocal(w.c.clone()),
        rest: w.mesh.position.clone(),
      }))

      // The *unsprung* assembly: everything below the strut that travels with the wheels rather than
      // with the aeroplane — the truck beam, the axles, the brake units, the sliding piston. The strut
      // compresses between this and the airframe, so these have to move together with the tyres.
      // Moving only the black rubber leaves the wheels hanging visibly off their own bogie, which is
      // how this looked before: the gear extended and the tyres detached from the truck they bolt to.
      //
      // No node names to go on (the GLB's are Sketchfab noise), so use geometry: anything whose centre
      // sits within a couple of wheel-radii of a bogie's wheel cluster belongs to that bogie.
      const clusters = ['N', 'L', 'R'].map((side) => {
        const ws = wheels.filter((w) => w.id.startsWith(side))
        const c = ws.reduce((a, w) => a.add(w.c.clone()), new THREE.Vector3()).divideScalar(ws.length || 1)
        return { c, reach: 2.4 * (ws.reduce((a, w) => a + w.r, 0) / (ws.length || 1)) }
      })
      const wheelSet = new Set(wheels.map((w) => w.mesh))
      const bs = new THREE.Vector3()
      model.traverse((o) => {
        const m = o as THREE.Mesh
        if (!m.isMesh || wheelSet.has(m)) return
        m.geometry.computeBoundingSphere()
        bs.copy(m.geometry.boundingSphere!.center).applyMatrix4(m.matrixWorld)
        if (clusters.some((cl) => bs.distanceTo(cl.c) < cl.reach)) unsprung.push({ mesh: m, rest: m.position.clone() })
      })
      pickable = wheels.map((w) => w.mesh)
      for (const w of wheels) {
        w.mesh.userData.tireId = w.id
        const pip = new THREE.Mesh(
          new THREE.TorusGeometry(w.r * 0.85, w.r * 0.16, 6, 20),
          new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, depthWrite: false }),
        )
        pip.position.copy(w.local)
        plane.add(pip)
        pips.set(w.id, pip)
      }
      // Frame the camera off the real airframe, not off guessed metres.
      const box = new THREE.Box3().setFromObject(model)
      const len = box.getSize(new THREE.Vector3()).x
      // Aircraft-LOCAL, not world: moveCam adds the follow offset itself. Feeding it a world bogie
      // (which carries the aircraft's position on final) applied that offset twice and flung the
      // camera to double the distance, staring at empty grass.
      const lefts = wheels.filter((w) => w.id.startsWith('L'))
      const bogie = lefts.reduce((a, w) => a.add(w.local), new THREE.Vector3()).divideScalar(lefts.length || 1)
      // Keep the field framing: it belongs to the airport, not the airframe, and buildAirport already
      // worked it out from the real runway extents.
      CAM = { ...camPresets(len, bogie), field: CAM.field }
      moveCam(camRef.current)
      applyAttitude(currentAttitude)

      paint(selectedRef.current, null)
      setLoading(false)
      // The mapping is the whole join between the 3D and the fleet data — say so out loud if it breaks.
      if (wheels.length !== FLEET_TIRES.length) {
        console.warn(`b777.glb has ${wheels.length} wheels but FLEET_TIRES has ${FLEET_TIRES.length}`)
      }
    })

    // The environment is the airport: sky, sun, haze and ground all come off the track. Dark theme
    // dims the whole world rather than recolouring it — a noon sky next to a dark dashboard reads as
    // a bug, and dusk is the honest way to keep both.
    const applyEnv = (tk: Track, t: Theme) => {
      const e = ENV[tk.env]
      const dim = t === 'dark' ? 0.42 : 1
      const shade = (hex: number) => new THREE.Color(hex).multiplyScalar(dim)

      const g = skyCanvas.getContext('2d')!
      const grad = g.createLinearGradient(0, 0, 0, 256)
      grad.addColorStop(0, `#${shade(e.skyTop).getHexString()}`)
      grad.addColorStop(0.82, `#${shade(e.skyBottom).getHexString()}`)
      grad.addColorStop(1, `#${shade(e.skyBottom).getHexString()}`)
      g.fillStyle = grad
      g.fillRect(0, 0, 1, 256)
      skyTex.needsUpdate = true

      scene.fog = new THREE.Fog(shade(e.skyBottom).getHex(), e.fog[0], e.fog[1])
      fogBase = e.fog
      ;(ground.material as THREE.MeshStandardMaterial).color.copy(shade(e.ground))

      // Swing the sun around with the runway heading, so no two airports are lit the same way.
      const a = (tk.headingDeg * Math.PI) / 180
      const [sx, sy, sz] = e.sunPos
      sun.position.set(sx * Math.cos(a) - sz * Math.sin(a), sy, sx * Math.sin(a) + sz * Math.cos(a))
      sun.color.copy(shade(e.sun))
      sun.intensity = e.sunIntensity * (t === 'dark' ? 0.75 : 1)
      hemi.color.copy(shade(e.ambient))
      hemi.groundColor.copy(shade(e.ground))

      // The tarmac: wet is dark and glossy, contaminated is pale and dull, dry is neither.
      const look = {
        dry: { color: 0xffffff, roughness: 0.95 },
        wet: { color: 0x7d848b, roughness: 0.28 }, // low roughness = the sheen that says "wet"
        contaminated: { color: 0xd9dee2, roughness: 0.99 },
      }[tk.surface]
      runwayMat.color.copy(shade(look.color)) // one material for the whole airport
      runwayMat.roughness = look.roughness
    }

    // Rebuilding the airport is cheap but not free, and the theme toggle must not trigger it.
    let builtFor = ''
    const applyTrack = (tk: Track, t: Theme) => {
      const key = `${tk.icao}/${tk.rwy}`
      if (key !== builtFor) {
        buildAirport(tk)
        builtFor = key
      }
      applyEnv(tk, t)
    }

    let currentAttitude = attitude
    let currentFrame: LandingFrame | undefined = frame
    const wheelPos = new THREE.Vector3()
    const cameraFollow = new THREE.Vector3()
    const cameraTarget = new THREE.Vector3()
    const invParent = new THREE.Matrix4()
    const localUp = new THREE.Vector3()
    const localOrigin = new THREE.Vector3()
    const applyPose = (a: Attitude, f?: LandingFrame) => {
      currentAttitude = a
      currentFrame = f
      const d = Math.PI / 180
      const pose = f?.pose ?? { ...a, xM: 0, yM: 0, zM: 0 }
      plane.rotation.set(pose.rollDeg * d, pose.crabDeg * d, pose.pitchDeg * d) // x=roll, y=crab, z=pitch
      plane.position.x = pose.xM
      plane.position.z = pose.zM

      // Where the wheels sit: the approach, then the runway. Bank lowers the down-wing tires, so raise
      // the aircraft by exactly enough to keep the lowest one on top of the runway rather than through
      // it. (Squat cancels out of this: the wheels were lifted by the same amount the airframe was
      // dropped, so their height above the runway is unchanged — which is the entire point.)
      let lowestTire = Infinity
      for (const w of wheels) {
        const bottomY = wheelPos.copy(w.local).applyEuler(plane.rotation).y - w.r
        lowestTire = Math.min(lowestTire, bottomY)
      }
      const wheelY = pose.yM + (wheels.length ? Math.max(0, -lowestTire) : 0)

      // THE STRUT, made visible. The airframe drops onto its gear, the gas spring pushes it part of the
      // way back out, it settles — and on a hard arrival it skips the tyres clear of the runway. The
      // GLB is rigid, so a squat cannot simply move it: that drives the tyres through the tarmac. Drop
      // the airframe, lift the wheel meshes by the same amount, and the wheels stay planted exactly
      // where the runway is while the fuselage does the moving. Which is what a strut is.
      const squat = f?.squatM ?? 0
      plane.position.y = wheelY - squat
      plane.updateMatrixWorld(true)

      // The offset has to be a real metre of world height, and getting it there is the fiddly part: the
      // wheel meshes hang deep inside the GLB's hierarchy under a chain of scales that multiply out to
      // roughly (0.096, 0.071, 0.071) — and it is *non-uniform*, so no single divisor undoes it. Push
      // the mesh a naive `squat` along its own local +Y and a 43 cm strut stroke arrives as 3 cm, which
      // is exactly nothing, and the gear looks welded. Going through the parent's inverse world matrix
      // converts one world metre of +Y into whatever that means down there, scale and rotation and all.
      const lift = (mesh: THREE.Mesh, rest: THREE.Vector3) => {
        const inv = invParent.copy(mesh.parent!.matrixWorld).invert()
        const local = localUp.set(0, 1, 0).applyMatrix4(inv).sub(localOrigin.set(0, 0, 0).applyMatrix4(inv))
        mesh.position.copy(rest).addScaledVector(local, squat)
      }
      for (const w of wheels) {
        lift(w.mesh, w.rest)
        const pip = pips.get(w.id)
        if (pip) pip.position.set(w.local.x, w.local.y + squat, w.local.z)
      }
      for (const u of unsprung) lift(u.mesh, u.rest) // the truck, axles and brakes come with the wheels
      const sel = wheels.find((w) => w.id === selectedRef.current)
      if (sel && ring.visible) ring.position.set(sel.local.x, sel.local.y + squat, sel.local.z)

      // Follow the aircraft in all three axes, not just along the runway. On short final it is a few
      // hundred metres out AND tens of metres up; tracking only x/z left the camera staring at the
      // grass under the approach path while the aircraft flew overhead, out of frame.
      //
      // Follow where the aircraft *is* (`wheelY`), NOT where its fuselage has been dragged to by the
      // gear (`plane.position.y`, which carries the squat). Track the squat and the camera sinks with
      // the airframe by exactly the amount the strut compressed — perfectly cancelling it. The gear
      // then strokes, recoils and skips in complete stillness, which is precisely the bug that hid the
      // whole strut model: correct simulation, correct render, camera subtracting the answer.
      cameraTarget.set(plane.position.x, wheelY, plane.position.z)
      const delta = cameraTarget.clone().sub(cameraFollow)
      if (delta.lengthSq() > 0) {
        camera.position.add(delta)
        controls.target.add(delta)
        cameraFollow.copy(cameraTarget)
        controls.update()
      }
    }
    const applyAttitude = (a: Attitude) => applyPose(a, currentFrame)
    const applyFrame = (f: LandingFrame | undefined) => applyPose(currentAttitude, f)

    // Placeholder until the airframe lands and tells us how big it is.
    let CAM = camPresets(70, new THREE.Vector3(-2, 1, -5))
    const moveCam = (p: CamPreset) => {
      const [pos, tgt] = CAM[p]
      // Every preset but FIELD is defined relative to the aircraft, so it rides along with it. FIELD
      // frames the aerodrome itself and stays put.
      const follow = p === 'field' ? ZERO : cameraFollow
      camera.position.copy(pos).add(follow)
      controls.target.copy(tgt).add(follow)
      controls.update()
    }

    const ray = new THREE.Raycaster()
    const ptr = new THREE.Vector2()
    const hit = (e: MouseEvent) => {
      const r = renderer.domElement.getBoundingClientRect()
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(ptr, camera)
      // Only the wheels are pickable — cheap, and a click can never land on the fuselage by mistake.
      return (ray.intersectObjects(pickable, false)[0]?.object.userData.tireId as string) ?? null
    }
    const onMove = (e: MouseEvent) => {
      const id = hit(e)
      renderer.domElement.style.cursor = id ? 'pointer' : 'grab'
      setHover(id)
    }
    const onClick = (e: MouseEvent) => {
      const id = hit(e)
      if (id) onSelect(id)
    }
    renderer.domElement.addEventListener('pointermove', onMove)
    renderer.domElement.addEventListener('click', onClick)

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = el
      if (!w || !h) return
      renderer.setSize(w, h) // updateStyle stays on: without it the canvas lays out at device-pixel size
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    const ro = new ResizeObserver(resize)
    ro.observe(el)
    resize()

    let raf = requestAnimationFrame(function tick() {
      controls.update()
      // Haze tuned for a wheel 15 m away is a wall of grey from 2 km up. Push the fog out with the
      // camera so close-ups keep their atmosphere and the field view can actually see the field.
      if (scene.fog instanceof THREE.Fog) {
        const d = camera.position.distanceTo(controls.target)
        scene.fog.near = fogBase[0]
        scene.fog.far = Math.max(fogBase[1], d * 3)
      }
      if (ring.visible) {
        const w = wheels.find((x) => x.id === selectedRef.current)
        if (w) ring.scale.setScalar(w.r * (1.3 + Math.sin(Date.now() / 320) * 0.07)) // pulse, so it reads at 12 px
      }
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    })

    applyTrack(track, theme)
    applyPose(attitude, frame)
    moveCam('gear')

    api.current = {
      setAttitude: applyAttitude,
      setFrame: applyFrame,
      setSelected: (id) => {
        selectedRef.current = id
        paint(id, null)
      },
      setHover: (id) => paint(selectedRef.current, id),
      repaint: () => paint(selectedRef.current, null),
      setCam: (p) => {
        camRef.current = p
        moveCam(p)
      },
      setEnv: applyTrack,
    }

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      renderer.domElement.removeEventListener('pointermove', onMove)
      renderer.domElement.removeEventListener('click', onClick)
      controls.dispose()
      renderer.dispose()
      el.removeChild(renderer.domElement)
    }
    // Built once; prop changes are pushed in imperatively below. Rebuilding a 2 MB airframe on a
    // slider drag would be absurd.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => api.current?.setAttitude(attitude), [attitude])
  useEffect(() => api.current?.setFrame(frame), [frame])
  useEffect(() => api.current?.setSelected(selected), [selected])
  useEffect(() => api.current?.setHover(hover), [hover])
  useEffect(() => api.current?.setCam(cam), [cam])
  useEffect(() => api.current?.setEnv(track, theme), [track, theme])

  const hovered = hover ? FLEET_TIRES.find((t) => t.id === hover) : null

  return (
    <div className="relative h-full w-full">
      <div ref={host} className="h-full w-full" />

      {loading && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
          Loading airframe…
        </div>
      )}

      <div className="absolute right-2 top-2 flex gap-1">
        {(['field', 'chase', 'side', 'gear'] as CamPreset[]).map((p) => (
          <button
            key={p}
            onClick={() => setCam(p)}
            aria-pressed={cam === p}
            className="border px-2 py-1 text-[9px] uppercase tracking-widest transition-colors"
            style={{
              borderColor: cam === p ? 'var(--primary)' : 'var(--line-2)',
              color: cam === p ? 'var(--primary)' : 'var(--ink-3)',
              background: 'color-mix(in srgb, var(--panel) 80%, transparent)',
            }}
          >
            {p}
          </button>
        ))}
      </div>

      {hovered && (
        <div className="pointer-events-none absolute left-2 top-2 border border-[var(--line-2)] bg-[var(--panel)]/90 px-2 py-1 text-[10px] uppercase tracking-widest text-[var(--ink-2)]">
          {hovered.id} · {hovered.serial} · {hovered.psi} psi
        </div>
      )}

      {/* Wheel strip: keyboard path, small-screen path, and the honest fallback when a wheel is
          12 px wide. The 3D is never the only way to pick a tire. */}
      <div className="absolute inset-x-0 bottom-0 flex flex-wrap justify-center gap-1 bg-gradient-to-t from-[var(--bg)] to-transparent p-2">
        {FLEET_TIRES.map((t) => {
          const on = t.id === selected
          const c = mockAllowed ? STATUS_HUE[statusOf(t)] : NO_FEED_HUE
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              onMouseEnter={() => setHover(t.id)}
              onMouseLeave={() => setHover(null)}
              aria-pressed={on}
              title={mockAllowed ? `${t.label} · ${t.psi} psi` : `${t.label} · no feed`}
              className="border px-1.5 py-1 text-[10px] tabular-nums tracking-widest transition-colors"
              style={{ borderColor: on ? 'var(--ink)' : c, color: on ? 'var(--ink)' : c, background: on ? `${c}33` : 'transparent' }}
            >
              {t.id}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** Asphalt with edge lines and a dashed centreline, drawn once. No image asset to ship. */
function runwayTexture(maxAnisotropy: number) {
  const c = document.createElement('canvas')
  c.width = 512 // along the runway — 50 m per tile
  c.height = 512 // across — the full 45 m
  const g = c.getContext('2d')!
  g.fillStyle = '#3a3d41'
  g.fillRect(0, 0, 512, 512)
  g.fillStyle = '#43464b' // patchy asphalt, so the surface isn't dead flat
  for (let i = 0; i < 40; i++) g.fillRect(Math.random() * 512, Math.random() * 512, 48, 20)
  g.fillStyle = '#d8d8d0'
  g.fillRect(0, 28, 512, 8)
  g.fillRect(0, 476, 512, 8)
  g.fillRect(40, 248, 280, 12) // centreline dash
  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(84, 1)
  // Max anisotropy, not a guessed 8: at a grazing angle the markings are exactly the case this
  // exists for, and the shimmer they were making is indistinguishable from the depth crawl.
  tex.anisotropy = maxAnisotropy
  return tex
}
