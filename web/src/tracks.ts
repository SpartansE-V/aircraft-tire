import { AIRPORTS, type Airport, type Runway } from './airports'
import type { Surface } from './sim'

// A track is: which airport, which runway end you land on, and what the day is like. Everything
// geometric — length, heading, where the threshold sits relative to the other runways — comes from
// airports.ts, which is generated from real coordinates. Nothing here is a number I typed by hand,
// because the last time I did that LAX's 25L was 300 m too long.

export type EnvKey = 'tropical' | 'coastal' | 'overcast' | 'rain' | 'desert' | 'highdesert' | 'snow'

type TrackInput = {
  icao: string
  rwy: string // the end you land on — its ident, its heading
  surface: Surface // today's state, not the pavement type
  oatC: number
  env: EnvKey
  note: string // why this track is interesting to a tire
}

export type Track = TrackInput & {
  name: string
  city: string
  lengthM: number
  elevFt: number
  headingDeg: number
  rwycc: number
}

const RWYCC: Record<Surface, number> = { dry: 6, wet: 4, contaminated: 2 }

const TRACK_INPUTS: TrackInput[] = [
  {
    icao: 'VVTS', rwy: '25R', surface: 'dry', oatC: 33, env: 'tropical',
    note: 'The short parallel, and the hottest air in the set — the brakes have the least room to dump heat',
  },
  {
    icao: 'KLAX', rwy: '25L', surface: 'dry', oatC: 21, env: 'coastal',
    note: 'The inboard south runway. Long, dry, sea level — the benign case everything else is measured against',
  },
  {
    icao: 'KJFK', rwy: '04L', surface: 'wet', oatC: 7, env: 'overcast',
    note: 'Wet and cold: µ drops and the rollout stretches — and 04L crosses 13R/31L, so a long stop crosses traffic',
  },
  {
    icao: 'EGLL', rwy: '27L', surface: 'wet', oatC: 11, env: 'rain',
    note: 'Rain on the southern parallel — the tires spend the most time hot and wet here',
  },
  {
    icao: 'OMDB', rwy: '12L', surface: 'dry', oatC: 43, env: 'desert',
    note: 'Ambient at 43 °C sits the bead close to the fuse plug before the brakes have done anything',
  },
  {
    icao: 'KDEN', rwy: '16R', surface: 'dry', oatC: 18, env: 'highdesert',
    note: 'A mile up, on the longest runway in North America — the same indicated speed is a faster touchdown',
  },
  {
    icao: 'PANC', rwy: '07R', surface: 'contaminated', oatC: -8, env: 'snow',
    note: 'Contaminated and freezing — µ collapses, the stop runs long, and the tread scrubs sideways',
  },
]

export const TRACKS: Track[] = TRACK_INPUTS.map((track) => {
  const a = active(track)
  return {
    ...track,
    name: a.airport.name,
    city: a.airport.city,
    lengthM: a.lengthM,
    elevFt: a.elevFt,
    headingDeg: a.headingDeg,
    rwycc: RWYCC[track.surface],
  }
})

/** The runway a track lands on, and where its threshold sits in the airport's own metric frame. */
export function active(track: Pick<TrackInput, 'icao' | 'rwy'>) {
  const airport: Airport = AIRPORTS[track.icao]
  const runway: Runway = airport.runways.find((r) => r.le === track.rwy || r.he === track.rwy)!
  const atLe = runway.le === track.rwy
  return {
    airport,
    runway,
    lengthM: runway.lengthM,
    widthM: runway.widthM,
    elevFt: airport.elevFt,
    headingDeg: atLe ? runway.leHdg : runway.heHdg,
    // The threshold you touch down on, and the far end you are trying not to run off.
    thrE: atLe ? runway.leE : runway.heE,
    thrN: atLe ? runway.leN : runway.heN,
    endE: atLe ? runway.heE : runway.leE,
    endN: atLe ? runway.heN : runway.leN,
  }
}

export type Env = {
  skyTop: number
  skyBottom: number // also the fog colour, so the horizon dissolves instead of ending
  ground: number
  sun: number
  sunIntensity: number
  ambient: number
  fog: [number, number] // near, far
  sunPos: [number, number, number]
}

// One environment per climate. Cheap and hand-tuned: a vertical sky gradient, a sun, a ground tint,
// and a fog that matches the horizon. No HDRI to download, nothing to fetch.
export const ENV: Record<EnvKey, Env> = {
  tropical: {
    skyTop: 0x4a8fd0, skyBottom: 0xd6ded0, ground: 0x3d5a30, sun: 0xfff2d8,
    sunIntensity: 3.0, ambient: 0xbfd4e8, fog: [400, 3000], sunPos: [-30, 70, 40],
  },
  coastal: {
    skyTop: 0x6aa6d8, skyBottom: 0xe2e6e4, ground: 0x6b7355, sun: 0xffeccc,
    sunIntensity: 2.6, ambient: 0xcdd8e2, fog: [350, 2600], sunPos: [50, 45, 30],
  },
  overcast: {
    skyTop: 0x8a949e, skyBottom: 0xb9c0c6, ground: 0x4a5340, sun: 0xd8dee4,
    sunIntensity: 1.3, ambient: 0xaeb6bd, fog: [250, 1800], sunPos: [-20, 80, 10],
  },
  rain: {
    skyTop: 0x5f6a74, skyBottom: 0x939ba3, ground: 0x3f4a38, sun: 0xc2cad2,
    sunIntensity: 1.0, ambient: 0x99a2aa, fog: [180, 1200], sunPos: [-40, 60, -20],
  },
  desert: {
    skyTop: 0x5b9bd5, skyBottom: 0xe8d9b8, ground: 0x9c8256, sun: 0xfff0cf,
    sunIntensity: 3.6, ambient: 0xdccfb4, fog: [500, 3600], sunPos: [20, 85, 10],
  },
  highdesert: {
    skyTop: 0x2f6fb8, skyBottom: 0xcdd9e2, ground: 0x7d7a55, sun: 0xffffff,
    sunIntensity: 3.3, ambient: 0xc4d2e0, fog: [600, 4200], sunPos: [-50, 70, 25],
  },
  snow: {
    skyTop: 0x7d93a8, skyBottom: 0xdfe6ec, ground: 0xd6dde2, sun: 0xeaf2ff,
    sunIntensity: 1.8, ambient: 0xd2dce6, fog: [220, 1600], sunPos: [-60, 25, 40], // low winter sun
  },
}
