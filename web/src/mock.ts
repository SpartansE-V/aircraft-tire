// One global switch: may mock telemetry appear on screen?
//
// Almost everything in this app is fed by FLEET_TIRES (src/data.ts) — pressures, grooves, defects,
// cycles, taxi, per-landing FOQA. It is invented. Two things are not: the RUL screen and the tire
// assessment panel, which both talk to the real service.
//
// Switch mock off and the invented panels leave the page. What is left is what this app actually has.
// That is the point of the switch: it is very easy to demo a wall of numbers and forget which of them
// exist. Nothing is fabricated to fill the gap — a feed we do not have shows as a feed we do not have.
//
// ponytail: useSyncExternalStore over a module variable — a shared boolean does not need a context
// provider, and this is the stdlib hook for exactly that.
import { useSyncExternalStore } from 'react'

let allowed = localStorage.getItem('mock') !== 'off'
const listeners = new Set<() => void>()

export function setMock(next: boolean) {
  allowed = next
  localStorage.setItem('mock', next ? 'on' : 'off')
  listeners.forEach((notify) => notify())
}

/** True when mock telemetry may be shown. */
export function useMock() {
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify)
      return () => listeners.delete(notify)
    },
    () => allowed,
  )
}
