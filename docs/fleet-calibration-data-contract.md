# Real fleet calibration data contract

The model cannot be calibrated from synthetic examples, accident reports, tire specification tables,
or aggregate plots. Calibration requires repeated measurements of uniquely identified tire casings
with the operational exposure between measurements.

The normalized row contract is `FleetTireInterval` in `app/calibration/schemas.py`. Source records are
newline-delimited JSON and must include:

- source-system and extract identifiers (these identifiers alone do not authenticate provenance);
- operator, aircraft tail, tire asset/casing, construction, and retread count;
- one canonical exact target identity: aircraft manufacturer/model/variant, tire
  manufacturer/part number/size, gear, and wheel position;
- timezone-aware UTC interval bounds and accumulated cycle counters;
- measured tread depth at both interval boundaries;
- measurement gauge identity and calibration validity;
- removal/defect outcome;
- pressure, temperature, landing, touchdown speed/sink/yaw, taxi, braking, and runway-exposure
  aggregates required by the current readiness contract, or explicit missing values that block it.

The schema rejects tread increases and exposure-event counts greater than interval cycles. The audit
also rejects mixed exact targets, inconsistent target identity for one casing, and overlapping time or
cycle intervals for a casing.

The supported `load_fleet_dataset` path reads the bounded file once, calculates SHA-256 over those
exact in-memory bytes, and parses the records from those same bytes. It returns a frozen
`FleetDatasetSnapshot`. Direct construction of Python models is not a provenance boundary; production
promotion must use the loader and retain the source extract and attestation.

`freeze_dataset_split` assigns whole `casing_serial_id` groups, not installation/tire-asset rows, to
training or validation. Its manifest contains the source digest and explicit casing/record membership.
`freeze_dataset_partitions` then creates distinct canonical training and holdout artifacts. Each embeds
its exact normalized rows and binds the source-snapshot digest, split-manifest digest, target identity,
casing IDs, and record IDs. Thus the two partition SHA-256 values differ while remaining traceable to
one predeclared source and split.

Calibration and validation evidence is canonical JSON. A calibration package contains the training
partition, predeclared policy, frozen per-record predictions, and report. A validation package contains
the holdout partition, predeclared policy, frozen predictions, report, and accountable acceptance
decision. The release loader verifies every file digest and schema, cross-checks target/model/source/
split/partition/policy identities, and recomputes MAE, RMSE, signed bias, and nearest-rank p90 absolute
error from the embedded rows and predictions. Editing a report and updating its checksum cannot create
a passing package.

The implemented evaluator validates only the scoped claim `TREAD_WEAR_RATE_POINT`. It does not validate
tread-depth interval coverage, cycles-to-threshold, threshold-event probabilities, severity classes,
recommendation policy, pressure counterfactuals, temporal generalization, or aircraft-tail
generalization. Governance requires those separate claims before operational authorization; one
wear-rate report cannot authorize the full API.

Default project-governance minima are 1,000 intervals, 100 distinct casings, 10 aircraft, and 20
observed wear-limit removals, with 20% of casings reserved for validation. These are initial
data-readiness gates, not proof of statistical adequacy. Engineering and statistical owners must freeze
the target-specific acceptance policy before generating holdout predictions.

## Evidence status and remaining operator-import gap

These contracts and unit tests use synthetic fixtures. The repository still contains no real operator
fleet/test extract, no completed calibration report, and no Boeing 737-800/APR04450 holdout result.
Consequently they do not change the release's `NOT_PERFORMED` calibration or validation status.

SHA-256 binding detects substitution after a snapshot is loaded; it does not authenticate who produced
the source data. Before a real dataset is accepted, an operator-side import package still needs a source
provenance manifest, keyed pseudonymization of tail/casing/tool identifiers, measurement-protocol and
gauge-calibration records for both interval boundaries, raw tread readings by groove and
circumferential location (including repeats and measurement uncertainty), exact target/applicability
confirmation, and an authorized source attestation. The current scalar start/end tread fields do not
preserve uneven-wear geometry and must not be presented as a complete inspection record. A future
operator importer must apply a versioned, predeclared aggregation rule to those raw readings rather than
inventing one inside the model. The source artifacts must be retained outside the model repository under
the operator's data-governance controls.

## Public-data finding

No public row-level commercial aircraft-tire dataset was found with repeated tread measurements,
per-landing exposure, tire identity, and removal outcomes. Relevant public evidence includes:

- [NASA TP-3626 Table 4 benchmark](public-physical-benchmarks.md): 12 exact published aggregate
  texture-depth/wear-rate pairs are retained in a checksum-bound artifact for non-target research;
  they are not APR04450 calibration rows;
- [NASA/FAA Boeing 727 tire-wear experiment](https://ntrs.nasa.gov/citations/19770011149): real
  repeated flight testing, but only representative figures are public;
- [NASA TP-1569 physical tire tests](https://ntrs.nasa.gov/citations/19800004758): useful wear-physics
  curves, but no pass-level raw dataset;
- [FAA Service Difficulty Reports](https://www.faa.gov/av-info/download_SDR): public event rows for
  hazard taxonomy, but no healthy denominator or tread history;
- [Bridgestone/JAL wear prediction program](https://www.bridgestone.com/corporate/news/2020061601.html):
  confirms operational feasibility, but publishes no raw data.

Therefore an operator/OEM data agreement or a controlled new measurement campaign is a hard external
dependency for real fleet calibration.
