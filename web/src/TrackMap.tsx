import { HUE } from './charts'
import { active, type Track } from './tracks'

// A plan view of the whole airport, from real runway-end coordinates: LAX's four parallels, JFK's
// 13/31 crossing the 04s, Denver's six. North is up and the runways are turned to their true
// bearings, so the layouts are recognisable — the point being that a landing does not happen on an
// isolated strip. The active runway is lit, and this landing's roll is drawn onto it: green with room
// to spare, amber when tight, red when the stop runs off the far end.

export default function TrackMap({ track, stopDistM }: { track: Track; stopDistM: number }) {
  const a = active(track)
  const { runways } = a.airport

  // Fit the whole field, in its own east/north metres, into the viewBox. Every airport is drawn at
  // whatever scale it needs, but each one keeps its true proportions.
  const xs = runways.flatMap((r) => [r.leE, r.heE])
  const ys = runways.flatMap((r) => [r.leN, r.heN])
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 2000)
  const PX = 66 / (span * 1.16) // metres -> SVG units, with a margin for the idents

  // East is +x, north is −y in SVG (screen y grows downward).
  const px = (e: number) => (e - cx) * PX
  const py = (n: number) => -(n - cy) * PX

  const over = Math.max(0, stopDistM - a.lengthM)
  const rollOk = over === 0 && a.lengthM - stopDistM > 300
  const rollHue = over > 0 ? HUE.crit : rollOk ? HUE.ok : HUE.warn

  // The roll runs from the threshold toward the far end, in real metres, so it is drawn to the same
  // scale as the runway it is on. Beyond the end it keeps going — into the grass.
  const dx = a.endE - a.thrE
  const dy = a.endN - a.thrN
  const dist = Math.hypot(dx, dy) || 1
  const along = (m: number) => ({ e: a.thrE + (dx / dist) * m, n: a.thrN + (dy / dist) * m })
  const rollEnd = along(Math.min(stopDistM, a.lengthM))
  const overEnd = along(stopDistM)

  return (
    <div className="border border-[var(--line)] bg-[var(--panel)] p-2">
      <div className="mb-1 flex items-baseline justify-between text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
        <span>
          {a.airport.icao} · {runways.length} rwy
        </span>
        <span>{a.lengthM} m</span>
      </div>

      <svg viewBox="-40 -40 80 80" className="w-full">
        <g style={{ fill: 'var(--ink-4)' }}>
          <circle cx="0" cy="0" r="36" fill="none" style={{ stroke: 'var(--line)' }} strokeWidth="0.4" strokeDasharray="1 2" />
          <text x="0" y="-32" textAnchor="middle" fontSize="5">N</text>
        </g>

        {/* every runway the airport has — the inactive ones are the context that makes this a place */}
        {runways.map((r) => {
          const on = r.le === track.rwy || r.he === track.rwy
          return (
            <line
              key={`${r.le}/${r.he}`}
              x1={px(r.leE)}
              y1={py(r.leN)}
              x2={px(r.heE)}
              y2={py(r.heN)}
              strokeWidth={on ? 3 : 2.2}
              strokeLinecap="round"
              style={{ stroke: on ? 'var(--ink-3)' : 'var(--line-2)' }}
            />
          )
        })}

        {/* the landing roll, on the active runway, to scale */}
        <line
          x1={px(a.thrE)}
          y1={py(a.thrN)}
          x2={px(rollEnd.e)}
          y2={py(rollEnd.n)}
          stroke={rollHue}
          strokeWidth="3"
          strokeLinecap="butt"
          opacity="0.85"
        />
        {over > 0 && (
          // the part of the stop the runway could not absorb
          <line
            x1={px(rollEnd.e)}
            y1={py(rollEnd.n)}
            x2={px(overEnd.e)}
            y2={py(overEnd.n)}
            stroke={HUE.crit}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray="1.5 1"
          />
        )}

        {/* the threshold you touch down on */}
        <circle cx={px(a.thrE)} cy={py(a.thrN)} r="1.6" fill={HUE.primary} />
        <text
          x={px(a.thrE)}
          y={py(a.thrN) - 3}
          textAnchor="middle"
          fontSize="4.5"
          style={{ fill: 'var(--primary)' }}
        >
          {track.rwy}
        </text>
      </svg>

      <div className="mt-1 flex justify-between text-[9px] uppercase tracking-widest">
        <span style={{ color: rollHue }}>
          {over > 0 ? `Overrun ${Math.round(over)} m` : `Stops in ${Math.round(stopDistM)} m`}
        </span>
        <span className="text-[var(--ink-4)]">hdg {Math.round(a.headingDeg)}°</span>
      </div>
    </div>
  )
}
