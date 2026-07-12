// Self-check for the API-facing defect vocabulary: node --experimental-strip-types src/data.check.ts
import assert from 'node:assert/strict'
import { FLEET_TIRES, knownDefects } from './data.ts'

// The API's enum is all damage. A defect either speaks that language or it is wear, and wear is tread
// depth, not a defect. Anything else is a defect the model would never hear about — or a 422.
for (const t of FLEET_TIRES) {
  for (const d of t.defects) {
    if (d.kind === 'damage') assert.ok(d.code, `${t.id}: damage defect has no API code: ${d.label}`)
    else assert.equal(d.code, undefined, `${t.id}: wear defect must not carry an API code: ${d.label}`)
  }
}

// What the mapper hands the API: damage only, deduped.
for (const t of FLEET_TIRES) {
  const codes = knownDefects(t)
  assert.equal(new Set(codes).size, codes.length, `${t.id}: duplicate defect codes`)
  assert.equal(codes.length, t.defects.filter((d) => d.kind === 'damage').length, `${t.id}: lost or invented a defect`)
}

// The fleet has to actually exercise both sides, or the loops above pass by being empty.
const withDamage = FLEET_TIRES.filter((t) => knownDefects(t).length > 0)
const withWearOnly = FLEET_TIRES.filter((t) => t.defects.length > 0 && knownDefects(t).length === 0)
assert.ok(withDamage.length > 0, 'no tyre carries damage — the withhold path is untested')
assert.ok(withWearOnly.length > 0, 'no tyre has wear-only defects — the "wear is not a defect" path is untested')

console.log(`ok — ${withDamage.length} tyres withhold on damage, ${withWearOnly.length} pass through with wear only`)
