# Public physical-test benchmarks

## Evidence boundary

Public NASA reports contain authentic aircraft-tire measurements, but they do not publish the
row-level longitudinal records required to calibrate or validate Boeing 737-800 / Bridgestone
APR04450 remaining-life forecasts. The active release therefore records these sources only as
non-target supporting benchmarks and keeps calibration and validation at `NOT_PERFORMED`.

## NASA TP-3626 Table 4

[NASA TP-3626](https://ntrs.nasa.gov/citations/19970021237) publishes an exact aggregate table of
wear rate and average texture depth for controlled Instrumented Tire-Test Vehicle trials. The test
used a new 20 x 4.4 Type VII, 14-ply bias tire for each tested surface, inflated to 350 psi and
loaded to 4,500 lb. Dry tests were run at approximately 25 mph and 8 degrees yaw. Wear rate is the
slope of tire-and-wheel weight loss against rollout distance, not an original pass-level reading.

The checksum-bound transcription is stored in
`app/model_releases/pilot-sim-2.0.0/evidence/nasa-tp-3626-ittv-table4.json`. It preserves all 18
published surface rows, including blank wear-rate cells, and contains 12 reported wear-rate/texture
pairs. The downloaded NASA PDF used for visual verification has SHA-256
`7b9057f5a409031a5ac6b41c63c07001c647ce548cf3cd338d9e6ceef9e51bb2`.

A deterministic ordinary-least-squares description of those 12 aggregate pairs gives an R-squared
of approximately 0.8503 between average texture depth and wear rate. This is a derived within-test
observation, not proof that the relationship or coefficient transfers to another tire, aircraft,
load, speed, pressure, runway, or operating regime.

The report states that 168 individual ITTV tests were conducted. Those were repeated test lengths,
not 168 independent tires. Its full-scale work used 44.5 x 16.0-21 Orbiter-design tires and 23
flight tests, but the recorded load, yaw, speed, temperature, side-force, and video time histories
are not published as data files. The [NTRS metadata API](https://ntrs.nasa.gov/api/citations/19970021237)
lists only the report PDF as a downloadable artifact.

## FAA Boeing 727 operations

The [1977 NASA/FAA field report](https://ntrs.nasa.gov/citations/19770011149) documents four Boeing
727 test sets containing 16 total 49 x 17 Type VII retreads. FAA personnel periodically measured
tread depth across and around the tires. For one standard-stock left-inboard tire, the report gives
exact exposure checkpoints of 38, 90, 194, and 261 total landing operations; it was removed at 261
when marker cords became visible.

The corresponding profiles have no numerical tread-depth scale. The published wear curves are
averages across tires, grooves, and circumference readings rather than per-tire rows. The report
also describes the sample as comparatively small and notes that operations were predominantly
training touch-and-go landings. The [NTRS metadata API](https://ntrs.nasa.gov/api/citations/19770011149)
lists no supplementary measurement file.

## NASA TP-1569

[NASA TP-1569](https://ntrs.nasa.gov/citations/19800004758) reports controlled braking and
cornering tests. `22 x 5.5` is the tire size, not a sample count. Limited tires were reused at two
yaw angles or slip ratios when possible. The report publishes wear-rate plots but not the original
weights, pass records, tire identifiers, replicate counts, or uncertainty estimates. Figure
coordinates would therefore be digitized approximations, not raw observations. The
[NTRS metadata API](https://ntrs.nasa.gov/api/citations/19800004758) again lists only the PDF.

## Permitted use

These sources can support physical plausibility checks, monotonicity tests, and future submodel
research. They cannot support target fleet calibration, independent APR04450 validation, approved
pressure or removal limits, maintenance action, serviceability, or dispatch eligibility. NASA's
records classify the reports as public and `GOV_PUBLIC_USE_PERMITTED`; no separate raw-data license
or supplemental dataset is provided.
