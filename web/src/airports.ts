// GENERATED from OurAirports (public domain): https://davidmegginson.github.io/ourairports-data/
// Runway ends are real coordinates, projected to metres east/north of the airport reference point —
// so the layouts are the true ones: LAX's four parallels, JFK's crossing 13/31, Denver's six.
// Regenerate rather than hand-edit; hand-edited numbers are how we ended up with a 3685 m 25L at LAX
// (it is 3381 m) and a 3658 m 16R at Denver (it is 4876 m).

export type Runway = {
  le: string // low-numbered end, e.g. "07L"
  he: string // high-numbered end, e.g. "25R"
  lengthM: number
  widthM: number
  leHdg: number // true heading when landing ON the le end's ident
  heHdg: number
  leE: number // metres east of the airport reference point
  leN: number // metres north
  heE: number
  heN: number
}

export type Airport = {
  icao: string
  name: string
  city: string
  elevFt: number
  runways: Runway[] // longest first
}

export const AIRPORTS: Record<string, Airport> = {
  VVTS: {
    icao: 'VVTS',
    name: 'Tan Son Nhat',
    city: 'Ho Chi Minh City',
    elevFt: 33,
    runways: [
      { le: '07R', he: '25L', lengthM: 3800, widthM: 45, leHdg: 69.0, heHdg: 249.0, leE: -1640, leN: -813, heE: 1968, heN: 545 },
      { le: '07L', he: '25R', lengthM: 3050, widthM: 45, leHdg: 69.0, heHdg: 249.0, leE: -1640, leN: -423, heE: 1203, heN: 679 },
    ],
  },
  KLAX: {
    icao: 'KLAX',
    name: 'Los Angeles',
    city: 'Los Angeles',
    elevFt: 125,
    runways: [
      { le: '7L', he: '25R', lengthM: 3930, widthM: 46, leHdg: 83.0, heHdg: 263.0, leE: -1301, leN: -773, heE: 2605, heN: -292 },
      { le: '7R', he: '25L', lengthM: 3382, widthM: 61, leHdg: 83.0, heHdg: 263.0, leE: -1023, leN: -984, heE: 2336, heN: -571 },
      { le: '6R', he: '24L', lengthM: 3310, widthM: 46, leHdg: 83.0, heHdg: 263.0, leE: -2465, leN: 481, heE: 825, heN: 887 },
      { le: '6L', he: '24R', lengthM: 2721, widthM: 46, leHdg: 83.0, heHdg: 263.0, leE: -2142, leN: 737, heE: 558, heN: 1070 },
    ],
  },
  KJFK: {
    icao: 'KJFK',
    name: 'John F. Kennedy',
    city: 'New York',
    elevFt: 13,
    runways: [
      { le: '13R', he: '31L', lengthM: 4423, widthM: 61, leHdg: 121.0, heHdg: 301.0, leE: -3158, leN: 997, heE: 652, heN: -1286 },
      { le: '04L', he: '22R', lengthM: 3682, widthM: 61, leHdg: 31.0, heHdg: 211.0, leE: -531, leN: -1942, heE: 1235, heN: 1041 },
      { le: '13L', he: '31R', lengthM: 3048, widthM: 61, leHdg: 121.0, heHdg: 301.0, leE: -919, leN: 2043, heE: 1691, heN: 473 },
      { le: '04R', he: '22L', lengthM: 2560, widthM: 61, leHdg: 30.6, heHdg: 210.6, leE: 762, leN: -1564, heE: 2063, heN: 640 },
    ],
  },
  EGLL: {
    icao: 'EGLL',
    name: 'London Heathrow',
    city: 'London',
    elevFt: 83,
    runways: [
      { le: '09L', he: '27R', lengthM: 3901, widthM: 50, leHdg: 90.0, heHdg: 270.0, leE: -2048, leN: 751, heE: 1850, heN: 772 },
      { le: '09R', he: '27L', lengthM: 3658, widthM: 50, leHdg: 90.0, heHdg: 270.0, leE: -1865, leN: -664, heE: 1793, heN: -645 },
    ],
  },
  OMDB: {
    icao: 'OMDB',
    name: 'Dubai',
    city: 'Dubai',
    elevFt: 62,
    runways: [
      { le: '12R', he: '30L', lengthM: 4447, widthM: 60, leHdg: 121.0, heHdg: 301.0, leE: -666, leN: 339, heE: 2405, heN: -1544 },
      { le: '12L', he: '30R', lengthM: 4351, widthM: 60, leHdg: 121.0, heHdg: 301.0, leE: -2071, leN: 1652, heE: 1001, heN: -232 },
    ],
  },
  KDEN: {
    icao: 'KDEN',
    name: 'Denver',
    city: 'Denver',
    elevFt: 5431,
    runways: [
      { le: '16R', he: '34L', lengthM: 4877, widthM: 61, leHdg: 180.5, heHdg: 0.5, leE: -1898, leN: 3982, heE: -1983, heN: -905 },
      { le: '07', he: '25', lengthM: 3658, widthM: 46, leHdg: 90.5, heHdg: 270.5, leE: -4546, leN: -2129, heE: -872, heN: -2152 },
      { le: '08', he: '26', lengthM: 3658, widthM: 46, leHdg: 90.5, heHdg: 270.5, leE: 1007, leN: 1956, heE: 4682, heN: 1912 },
      { le: '16L', he: '34R', lengthM: 3658, widthM: 46, leHdg: 180.5, heHdg: 0.5, leE: -1128, leN: 4116, heE: -1128, heN: 454 },
      { le: '17L', he: '35R', lengthM: 3658, widthM: 46, leHdg: 180.5, heHdg: 0.5, leE: 2802, leN: 554, heE: 2717, heN: -3120 },
      { le: '17R', he: '35L', lengthM: 3658, widthM: 46, leHdg: 180.5, heHdg: 0.5, leE: 1178, leN: 130, heE: 1093, heN: -3532 },
    ],
  },
  PANC: {
    icao: 'PANC',
    name: 'Ted Stevens Anchorage',
    city: 'Anchorage',
    elevFt: 152,
    runways: [
      { le: '07R', he: '25L', lengthM: 3780, widthM: 61, leHdg: 90.0, heHdg: 270.0, leE: -2700, leN: -1246, heE: 1069, heN: -1238 },
      { le: '15', he: '33', lengthM: 3312, widthM: 61, leHdg: 165.0, heHdg: 345.0, leE: -1179, leN: 2307, heE: -317, heN: -886 },
      { le: '07L', he: '25R', lengthM: 3231, widthM: 46, leHdg: 90.0, heHdg: 270.0, leE: -846, leN: -1028, heE: 2375, heN: -1023 },
    ],
  },
}
