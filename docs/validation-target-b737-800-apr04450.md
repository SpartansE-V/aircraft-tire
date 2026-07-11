# First validation target: Boeing 737-800 / Bridgestone APR04450 main tire

## Status

`PUBLIC_REFERENCE_TARGET_ONLY`

This target is specific enough to organize data collection and validation, but it is not yet an
approved installation configuration, calibrated model, or maintenance/dispatch authorization.

## Public-reference identity

| Field | Public-reference value |
|---|---|
| Aircraft | Boeing 737-800, 737 Next Generation |
| FAA type certificate | A16WE |
| Gear position | Main landing gear |
| Manufacturer | Bridgestone |
| Tire part number | APR04450 |
| Construction | RRR radial, tubeless |
| Size | H44.5 × 16.5R21 |
| Strength index | 30 PR |
| Speed rating | 235 mph |
| Rated load | 48,400 lb per tire |
| Rated pressure | 230 psi, unloaded reference value |
| New mold skid depth | 0.51 in / 12.95 mm |
| Tread design | CB |
| Qualification references reported by manufacturer | TSO-C62e; Boeing S294W502 Rev M |

Sources:

- [Bridgestone Aircraft Tire Application Table, December 2022, pp. 100–101](https://www.bridgestone.com/products/aircraft/products/applications/pdf/BS_AC_Manual_2022_P.100-101.pdf)
- [Bridgestone Radial Tire Specifications, December 2022, pp. 108–109](https://www.bridgestone.com/products/aircraft/products/applications/pdf/BS_AC_Manual_2022_P.102-109.pdf)
- [Bridgestone Data Sheet Terminology, pp. 98–99](https://www.bridgestone.com/products/aircraft/products/applications/pdf/BS_AC_Manual_2022_P.98-99.pdf)
- [FAA Boeing 737 Flight Standardization Board Report, Revision 17](https://www.faa.gov/sites/faa.gov/files/2022-08/737_FSB_Report.pdf)
- [FAA Technical Standard Orders](https://www.faa.gov/aircraft/air_cert/design_approvals/tso)

## Safety boundary

The Bridgestone application table is general reference information and requires confirmation for
the particular aircraft type, series, and configuration. A TSO authorization establishes minimum
article performance; the FAA explicitly states that it is not installation approval. The 230 psi
value is an unloaded reference, not a service-pressure instruction. The 0.51-inch value is new-tire
geometry, not an approved removal threshold.

Before this target can be marked installation-controlled, current controlled Boeing and operator
data must establish:

- aircraft serial and modification applicability;
- wheel and brake assembly plus eligible tire part number;
- loaded/unloaded cold service pressure and measurement method;
- radial/bias mixability and axle-pairing rules;
- inspection, wear, removal, retread, and abnormal-event limits;
- controlled document identifiers, revisions, effective dates, and approvers.

Until those items and validation evidence exist, the API must remain scenario-planning only.
