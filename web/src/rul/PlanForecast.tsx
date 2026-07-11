import { useMemo, useState } from 'react'
import { Card } from '../ui'
import {
  useRulPredictions,
  useWheelStatus,
  useWorklist,
  type FlightConditions,
  type NgafidFlightSensors,
  type RulPredictionRequest,
  type WheelPosition,
  type WheelStatusResponse,
} from './api'
import { CANON_POSITIONS, fmtDate, fmtLandings, POSITION_LABEL, RUL_STATUS_META, severityInk } from './positions'
import TireImageCard from '../TireImageCard'

const inputCls =
  'w-full border border-[var(--line-2)] bg-[var(--panel)] px-2 py-1 text-xs tabular-nums text-[var(--ink-2)] outline-none focus:border-[var(--primary)]'

type MountedWheel = { position: WheelPosition; status?: WheelStatusResponse; loading: boolean; error: boolean }

const DEFAULT_CONDITIONS: FlightConditions = {
  landing_load_factor: 1,
  braking_energy_factor: 1,
  takeoff_severity_factor: 1,
  taxi_heat_factor: 1,
  temperature_factor: 1,
  inflation_factor: 1,
  runway_roughness_factor: 1,
  hard_landing_factor: 1,
  crosswind_factor: 1,
}

// Only conditions WITHOUT an NGAFID sensor equivalent live here — so the two input groups never
// double-count. Landing load, hard landing and temperature were dropped because the sensor block's
// NormAc, VSpd and OAT already carry them (they stay at 1.0 in the request).
const FACTOR_FIELDS: { key: keyof FlightConditions; label: string; min: number; max: number }[] = [
  { key: 'braking_energy_factor', label: 'Braking energy', min: 0.5, max: 2 },
  { key: 'takeoff_severity_factor', label: 'Takeoff / RTO', min: 0.5, max: 2 },
  { key: 'taxi_heat_factor', label: 'Taxi heat', min: 0.5, max: 1.5 },
  { key: 'inflation_factor', label: 'Underinflation', min: 1, max: 1.8 },
  { key: 'runway_roughness_factor', label: 'Runway roughness', min: 1, max: 1.5 },
  { key: 'crosswind_factor', label: 'Crosswind', min: 1, max: 1.5 },
]

// Reference (fleet-average) readings: an all-default sensor block is a normal cycle (multiplier 1.0).
const DEFAULT_SENSORS: NgafidFlightSensors = {
  indicated_airspeed_kt: 140,
  vertical_speed_fpm: 180,
  normal_acceleration_g: 1.0,
  outside_air_temperature_c: 15,
  altitude_msl_ft: 0,
}

// The five NGAFID FDR channels that physically drive tire wear (of the dataset's 23 sensors).
const SENSOR_FIELDS: {
  key: keyof NgafidFlightSensors
  ngafid: string
  label: string
  unit: string
  min: number
  max: number
  step: number
  hint: string
}[] = [
  { key: 'indicated_airspeed_kt', ngafid: 'IAS', label: 'Airspeed', unit: 'kt', min: 40, max: 250, step: 1, hint: 'Touchdown speed → spin-up scrub (∝ speed²)' },
  { key: 'vertical_speed_fpm', ngafid: 'VSpd', label: 'Sink rate', unit: 'fpm', min: 0, max: 1500, step: 10, hint: 'Descent rate → touchdown impact' },
  { key: 'normal_acceleration_g', ngafid: 'NormAc', label: 'Landing g', unit: 'g', min: 0.5, max: 4, step: 0.05, hint: 'Measured vertical g → peak tire load' },
  { key: 'outside_air_temperature_c', ngafid: 'OAT', label: 'Air temp', unit: '°C', min: -40, max: 55, step: 1, hint: 'Warmer rubber → faster tread wear' },
  { key: 'altitude_msl_ft', ngafid: 'AltMSL', label: 'Field alt', unit: 'ft', min: -1500, max: 15000, step: 100, hint: 'Thin air → faster true touchdown' },
]

export default function PlanForecast() {
  const [tail, setTail] = useState('')
  const [newLandings, setNewLandings] = useState('0')
  const [clientError, setClientError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<RulPredictionRequest[]>([])
  const [conditions, setConditions] = useState<FlightConditions>(DEFAULT_CONDITIONS)
  const [sensors, setSensors] = useState<NgafidFlightSensors>(DEFAULT_SENSORS)
  const [photoPosition, setPhotoPosition] = useState<WheelPosition | null>(null)

  const fleet = useWorklist(50, null)
  const tails = useMemo(
    () => [...new Set((fleet.data?.wheels ?? []).map((wheel) => wheel.tail_number))].sort(),
    [fleet.data],
  )

  // Fixed hook order: load every canonical mounted wheel for the selected aircraft.
  const nlgL = useWheelStatus(tail || null, 'nlg_l')
  const nlgR = useWheelStatus(tail || null, 'nlg_r')
  const mlgLIn = useWheelStatus(tail || null, 'mlg_l_inbd')
  const mlgLOut = useWheelStatus(tail || null, 'mlg_l_outbd')
  const mlgRIn = useWheelStatus(tail || null, 'mlg_r_inbd')
  const mlgROut = useWheelStatus(tail || null, 'mlg_r_outbd')
  const wheelQueries = [nlgL, nlgR, mlgLOut, mlgLIn, mlgRIn, mlgROut]
  const mounted: MountedWheel[] = CANON_POSITIONS.map((position, index) => ({
    position,
    status: wheelQueries[index].data,
    loading: wheelQueries[index].isLoading,
    error: wheelQueries[index].isError && wheelQueries[index].error?.status !== 404,
  }))

  const predictions = useRulPredictions(submitted)
  const isLoadingWheels = tail !== '' && mounted.some((wheel) => wheel.loading)

  const run = () => {
    const additional = Number(newLandings)
    if (!tail) {
      setClientError('Select an aircraft first.')
      return
    }
    if (newLandings.trim() === '' || !Number.isFinite(additional) || additional < 0) {
      setClientError('New landings must be a number ≥ 0.')
      return
    }
    const invalidFactor = FACTOR_FIELDS.find(({ key, min, max }) => {
      const value = conditions[key]
      return !Number.isFinite(value) || value < min || value > max
    })
    if (invalidFactor) {
      setClientError(`${invalidFactor.label} factor must be between ${invalidFactor.min} and ${invalidFactor.max}.`)
      return
    }
    const invalidSensor = SENSOR_FIELDS.find(({ key, min, max }) => {
      const value = sensors[key]
      return !Number.isFinite(value) || value < min || value > max
    })
    if (invalidSensor) {
      setClientError(`${invalidSensor.ngafid} (${invalidSensor.label}) must be between ${invalidSensor.min} and ${invalidSensor.max} ${invalidSensor.unit}.`)
      return
    }
    const available = mounted.flatMap((wheel) => (wheel.status ? [wheel.status] : []))
    if (available.length === 0 || isLoadingWheels) {
      setClientError('Wait for the mounted tire data to finish loading.')
      return
    }
    setClientError(null)
    setSubmitted(
      available.map((wheel) => ({
        position: wheel.position,
        current_cycles: wheel.current_cycles,
        planned_landings: additional,
        flight_conditions: conditions,
        flight_sensors: sensors,
        landings_per_day: wheel.utilization_landings_per_day,
        readings: wheel.readings,
        as_of_date: wheel.as_of_date,
      })),
    )
  }

  const rankedResults = submitted
    .map((request, index) => ({
      request,
      prediction: predictions[index],
      baseline: mounted.find((wheel) => wheel.position === request.position)?.status,
    }))
    .sort((a, b) => (b.baseline?.priority ?? 0) - (a.baseline?.priority ?? 0))

  const worst = rankedResults.find((row) => row.prediction.data)

  return (
    <Card title="Log Flight & Update Tire RUL" tag="all mounted tires · position-weighted priority">
      <div className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[2fr_1fr_auto] md:items-end">
          <label className="block">
            <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Aircraft (tail)</span>
            <select
              value={tail}
              onChange={(event) => {
                setTail(event.target.value)
                setSubmitted([])
                setPhotoPosition(null)
                setClientError(null)
              }}
              className={`${inputCls} mt-1`}
            >
              <option value="">— select aircraft —</option>
              {tails.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">New landings to apply</span>
            <input
              type="number"
              min={0}
              value={newLandings}
              onChange={(event) => setNewLandings(event.target.value)}
              className={`${inputCls} mt-1`}
            />
          </label>
          <button
            onClick={run}
            disabled={!tail || isLoadingWheels}
            className="border border-[var(--primary)] px-3 py-1.5 text-[10px] uppercase tracking-widest text-[var(--primary)] transition-colors hover:bg-[var(--primary-soft)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            ▸ Run all tires
          </button>
        </div>

        <div className="border-t border-dashed border-[var(--line)] pt-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Flight sensor readings · NGAFID FDR</span>
            <button
              onClick={() => setSensors(DEFAULT_SENSORS)}
              className="text-[9px] uppercase tracking-widest text-[var(--primary)]"
            >
              Reset to reference
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-5">
            {SENSOR_FIELDS.map(({ key, ngafid, label, unit, min, max, step, hint }) => (
              <label key={key} className="block" title={hint}>
                <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
                  {ngafid} · {label} <span className="text-[var(--ink-3)]">({unit})</span>
                </span>
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={sensors[key]}
                  onChange={(event) => setSensors((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  className={`${inputCls} mt-1`}
                />
              </label>
            ))}
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-4)]">
            The five NGAFID flight-data-recorder channels that drive tire wear — spin-up scrub, touchdown load and thermal wear. The backend converts these raw readings into a position-weighted exposure and combines it with the wear factors below.
          </p>
        </div>

        <div className="border-t border-dashed border-[var(--line)] pt-3">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-[10px] uppercase tracking-widest text-[var(--ink-4)]">Landing &amp; takeoff wear factors</span>
            <button
              onClick={() => setConditions(DEFAULT_CONDITIONS)}
              className="text-[9px] uppercase tracking-widest text-[var(--primary)]"
            >
              Reset to normal (1.0)
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-5">
            {FACTOR_FIELDS.map(({ key, label, min, max }) => (
              <label key={key} className="block">
                <span className="text-[9px] uppercase tracking-widest text-[var(--ink-4)]">{label}</span>
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={0.05}
                  value={conditions[key]}
                  onChange={(event) => setConditions((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  className={`${inputCls} mt-1`}
                />
              </label>
            ))}
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-[var(--ink-4)]">
            1.0 is a normal fleet-average cycle. The backend applies bounded, position-specific sensitivities; severe factors reduce predicted RUL.
          </p>
        </div>

        {clientError && <p className="text-[10px] text-[var(--crit)]">{clientError}</p>}

        {tail && (
          <div className="border-t border-dashed border-[var(--line)] pt-3">
            <div className="mb-2 flex flex-wrap justify-between gap-2 text-[10px] uppercase tracking-widest text-[var(--ink-4)]">
              <span>{isLoadingWheels ? 'Loading mounted tires…' : `${mounted.filter((wheel) => wheel.status).length} mounted tires loaded`}</span>
              <span className="text-[var(--primary)]">Click a wheel to screen a photo</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[11px]">
                <thead className="border-b border-[var(--line)] text-[9px] uppercase tracking-widest text-[var(--ink-4)]">
                  <tr>
                    <th className="py-2 pr-3 font-normal">Wheel position</th>
                    <th className="py-2 pr-3 text-right font-normal">Landed cycles</th>
                    <th className="py-2 pr-3 text-right font-normal">Position priority</th>
                    <th className="py-2 pr-3 text-right font-normal">Wear exposure</th>
                    <th className="py-2 pr-3 text-right font-normal">Predicted RUL</th>
                    <th className="py-2 font-normal">Condition</th>
                  </tr>
                </thead>
                <tbody>
                  {(submitted.length > 0 ? rankedResults : mounted.map((wheel) => ({ baseline: wheel.status, request: null, prediction: null }))).map((row, index) => {
                    const baseline = row.baseline
                    const prediction = row.prediction
                    const position = baseline?.position ?? row.request?.position ?? CANON_POSITIONS[index]
                    const picked = photoPosition === position
                    return (
                      <tr
                        key={position}
                        onClick={() => setPhotoPosition(picked ? null : position)}
                        aria-selected={picked}
                        className="cursor-pointer border-b border-[var(--line)] transition-colors last:border-0 hover:bg-[var(--panel)]"
                        style={picked ? { background: 'var(--primary-soft)' } : undefined}
                      >
                        <td className="py-2 pr-3 text-[var(--ink-2)]">
                          <span style={picked ? { color: 'var(--primary)' } : undefined}>
                            {picked ? '▸ ' : ''}
                            {POSITION_LABEL[position]}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">{baseline ? fmtLandings(baseline.current_cycles) : '—'}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{baseline?.priority.toFixed(3) ?? '—'}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {prediction?.data ? `${prediction.data.wear_exposure_multiplier.toFixed(2)}×` : '—'}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums">
                          {prediction?.isLoading ? '…' : prediction?.data ? `${fmtLandings(prediction.data.rul_landings.median)} ldg` : '—'}
                        </td>
                        <td className="py-2">
                          {prediction?.data ? (
                            <span style={{ color: severityInk(prediction.data.status.severity) }}>
                              {RUL_STATUS_META[prediction.data.status.status].label}
                            </span>
                          ) : baseline ? (
                            <span style={{ color: severityInk(baseline.severity) }}>{RUL_STATUS_META[baseline.status].label}</span>
                          ) : mounted[index]?.error ? <span className="text-[var(--crit)]">Unavailable</span> : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {photoPosition && (
              <div className="mt-3">
                <TireImageCard
                  id={`${tail}:${photoPosition}`}
                  aircraftId={tail}
                  label={`${tail} · ${POSITION_LABEL[photoPosition]}`}
                />
              </div>
            )}
          </div>
        )}

        {worst?.prediction.data && worst.baseline && (
          <p className="text-[10px] leading-relaxed text-[var(--ink-4)]">
            Aircraft planning status follows the highest-priority tire: <span className="text-[var(--ink-2)]">{POSITION_LABEL[worst.request.position]}</span>
            {' '}· RUL {fmtLandings(worst.prediction.data.rul_landings.median)} landings · snapshot {fmtDate(worst.baseline.as_of_date)}.
          </p>
        )}
      </div>
    </Card>
  )
}
