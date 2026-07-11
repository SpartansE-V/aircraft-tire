# Research: Aircraft Tire Forecasting, Limits, and Simulation Platform

Research date: 11 July 2026
Purpose: product and engineering discovery for a real-world aircraft-tire condition-monitoring,
forecasting, and scenario-simulation system.

## Executive conclusion

A useful production system should not answer only “how severe was this landing?” It should maintain a
digital record for each physical tire, ingest its measured condition and operating history, apply
authoritative maintenance limits, forecast wear with uncertainty, estimate separate unscheduled-removal
risk, and simulate future routes or operating scenarios.

The phrase **maximum condition the tire can hold** must mean the approved envelope for the exact tire
part number and aircraft installation—not a value invented by a prediction model. Aircraft-tire load and
speed ratings are based on qualification tests, and the approved installation must not exceed those
ratings under critical loading conditions. [EASA ETSO-C62e](https://www.easa.europa.eu/download/etso/ETSO-C62e_CS-ETSO_7.pdf), [EASA CS 25.733](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25)

Forecasts should be decision support for inspection and inventory planning. They must not declare a tire
“safe to fly,” approve dispatch, extend an approved maintenance interval, or override the Aircraft
Maintenance Manual (AMM), Component Maintenance Manual (CMM), Instructions for Continued
Airworthiness (ICA), or operator-approved maintenance programme. Bridgestone and Goodyear both state
that airframe/wheel instructions take precedence over their general tire guidance. [Bridgestone Care and Maintenance](https://www.bridgestone.com/products/aircraft/candm/), [Goodyear 2024 Aircraft Tire Care and Maintenance Manual](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf)

## 1. Safety and regulatory baseline

- FAA AC 20-97B is active guidance for aircraft-tire installation, inflation, maintenance, removal, and
  operational practices, but it is guidance rather than a regulation. [FAA AC 20-97B](https://www.faa.gov/airports/resources/advisory_circulars/index.cfm/go/document.information/documentID/22044)
- The FAA calls correct inflation pressure the single most effective preventive-maintenance task and
  recommends pressure checks on cold assemblies, normally daily. [FAA AC 20-97B, pp. 3–4](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf)
- FAA guidance says an assembly operating below 90% of minimum loaded service pressure should be
  removed; below 80%, both that assembly and its axle mate should be removed. These are generic FAA
  recommendations and do not replace the applicable AMM/CMM. [FAA AC 20-97B, p. 4](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf)
- EASA CS 25.733 requires a means to minimize operation below minimum serviceable inflation pressure;
  compliance may use an ICA pressure-check task or an installed monitoring system. EASA guidance says
  checks should ordinarily be daily so no more than 48 hours elapse unless a longer interval is
  substantiated. [EASA CS 25.733(f) and AMC 25.733(f)](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25)
- EASA's rulemaking analysis found pressure-related events dominant in the reviewed historical dataset
  and noted that underinflation in one tire of a multi-wheel assembly can be visually difficult to detect
  because the companion tire carries the load. [EASA RMT.0586](https://www.easa.europa.eu/en/downloads/22543/en)
- EASA requires TPMS development assurance to account for both missed alerts and false indications, and
  the ICA must preserve system calibration. [EASA AMC 25.733(f)](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25)
- SAE ARP6137 defines aircraft TPMS as electronically measuring and reporting current pressure and sets
  system-function and minimum-performance guidance for ground or flight-deck systems. [SAE ARP6137](https://saemobilus.sae.org/standards/arp6137-tire-pressure-monitoring-systems-tpms-aircraft)
- Tire repair and retread prediction must preserve casing identity and maintenance history because FAA
  AC 145-4A covers approved inspection, repair, alteration, retread process specifications, and
  nondestructive inspection. [FAA AC 145-4A](https://www.faa.gov/regulations_policies/advisory_circulars/index.cfm/go/document.information/documentID/22713)

## 2. What “maximum condition” should mean

There is no safe universal maximum for “a main tire” or “a nose tire.” The system must resolve the exact
aircraft, wheel position, approved tire part number, construction, and current maintenance-document
revision before presenting limits.

| Limit shown by the product | Authoritative meaning | Source of truth |
| --- | --- | --- |
| Rated load | Maximum permissible static load at the specified rated inflation pressure. [ETSO-C62e](https://www.easa.europa.eu/download/etso/ETSO-C62e_CS-ETSO_7.pdf) | Approved tire data, aircraft AMM/CMM, type-design data |
| Speed rating | Maximum ground speed at which the tire has been qualification-tested. [ETSO-C62e](https://www.easa.europa.eu/download/etso/ETSO-C62e_CS-ETSO_7.pdf) | Approved tire data and aircraft installation approval |
| Rated pressure | Unloaded inflation pressure associated with rated load and specified deflection. [ETSO-C62e](https://www.easa.europa.eu/download/etso/ETSO-C62e_CS-ETSO_7.pdf) | AMM/CMM and approved tire data—not a generic model default |
| Minimum serviceable pressure | Aircraft type-certificate holder's pressure below which tire damage may occur. [EASA AMC 25.733(f)](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25) | ICA/AMM and operator maintenance programme |
| Wheel-position load | Depends on aircraft weight, centre of gravity, gear geometry, braking/ground reactions, and multi-wheel configuration—not landing weight alone. [EASA CS 25.731–25.733](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25) | Aircraft engineering/load model or approved source |
| Tire-specific specification | Part number, construction, ply rating, speed rating, rated load, rated pressure, dimensions, and skid depth vary by tire. [Goodyear Aircraft Tire DataBook](https://www.goodyearaviation.com/resources/tiredatabook.html), [Bridgestone tire specifications](https://www.bridgestone.com/products/aircraft/products/applications/) | Versioned OEM data catalogue |
| In-service removal condition | Pressure loss, exposed casing/belt, cuts, bulges, separation, heat damage, flat spots, FOD, or atypical events can require removal before tread wear-out. [FAA AC 20-97B, pp. 4–6](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) | Current AMM/CMM/operator procedure plus qualified inspection |

The website should therefore show two distinct panels:

1. **Approved limits** — read-only values with source document, revision, applicability, and effective
   date.
2. **Predicted condition** — estimates, confidence intervals, data freshness, model version, and explicit
   “decision support only” wording.

## 3. Degradation and removal drivers the model must cover

| Driver | Evidence and modeling implication |
| --- | --- |
| Cold inflation pressure and leak rate | Incorrect inflation drives deflection, flex heating, uneven wear, and casing fatigue; pressure must be normalized for temperature and compared with the approved loaded/unloaded target. [Goodyear manual, pp. 19–21](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf), [Bridgestone pressure control](https://www.bridgestone.com/products/aircraft/candm/care_win03.html) |
| Tire temperature | Operational temperature can remain elevated for hours, so a hot reading is not directly interchangeable with cold service pressure. [Goodyear manual, p. 19](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf) |
| Load per tire | Underinflation and overloading both increase internal shear and reduce life; per-tire load should be estimated from weight, CG, gear position, and loading configuration. [Goodyear manual, pp. 47–49](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf), [EASA CS 25.733](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25) |
| Taxi speed and distance | Both increase internal heat; Goodyear's tests show temperature rising with taxi speed, distance, and underinflation, while FAA guidance warns that high load, sideload, taxi speed, and distance can compromise integrity. [Goodyear manual, pp. 42–44](https://www.goodyearaviation.com/resources/pdf/aviation-tire-care-2024.pdf), [FAA AC 20-97B, p. 5](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) |
| Touchdown speed, sink rate, and yaw/slip | A published aircraft-tire touchdown digital twin used touchdown speed, sink rate, yaw angle, and tire condition and produced probabilistic failure estimates. [Zakrajsek and Mall, AIAA 2017](https://scholar.afit.edu/facpub/2057/) |
| Crosswind and tight turns | The useful physical variable is lateral slip/yaw or scrub, not crosswind alone; crosswind landing and tight turns can produce lateral scoring, cuts, chunking, or internal damage. [Dunlop DM1172, pp. 42–47](https://www.dunlopaircrafttyres.co.uk/media/1265/dunlop-tcmm-dm1172-issue-11.pdf), [FAA AC 20-97B, p. 5](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) |
| Braking and brake heat | Locked-wheel braking can create flat spots, while abnormal brake heat can damage the bead region; capture anti-skid events, brake energy/temperature, rejected takeoff, and heavy-braking indicators where available. [Dunlop DM1172, pp. 38–39 and 52](https://www.dunlopaircrafttyres.co.uk/media/1265/dunlop-tcmm-dm1172-issue-11.pdf), [FAA AC 20-97B, p. 5](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) |
| Runway/taxiway surface and FOD | FAA identifies FOD as the most common cause of premature tire removal; this means wear-out life and unscheduled-removal risk must be modeled separately. [FAA AC 20-97B, pp. 4 and 6](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) |
| Measured tread and damage | Tread depth alone is insufficient: cuts, bulges, separations, exposed structure, contamination, flat spots, and heat damage can control removal. [FAA AC 20-97B, pp. 5–6](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf), [Bridgestone examination guide](https://www.bridgestone.com/products/aircraft/eandr/) |
| Tire identity and lifecycle | Construction, tire model, casing serial, new/retread state, retread count, installation, removal, and repair history change the applicable baseline and labels. [FAA AC 145-4A](https://www.faa.gov/regulations_policies/advisory_circulars/index.cfm/go/document.information/documentID/22713), [Goodyear DataBook](https://www.goodyearaviation.com/resources/tiredatabook.html) |

## 4. Existing products and platforms

### Tire-specific aviation products

| Product | Publicly documented inputs | Publicly documented outputs/capabilities | Product lesson |
| --- | --- | --- | --- |
| Michelin/Safran PresSense | Embedded pressure sensor, tire identity via local RFID reading, smartphone capture, and retained database records. [Safran PresSense announcement](https://www.safran-group.com/pressroom/michelin-and-safran-present-first-connected-tyre-aircraft-2017-06-20) | Remote pressure reading, smartphone display, database history, and data usable for subsequent predictive-maintenance analysis; Azul selected it for about 110 Airbus and Embraer aircraft. [Michelin/Azul 2023](https://www.michelin.com/en/publications/group/azul-selects-the-pressense-connected-tire-from-safran-and-michelin-to-equip-its-airbus-a320s-and-a321s-and-embraer-195-e12s-and-195-e2s) | Persistent measurements and tire-level identity are more valuable than one-off manual calculations. |
| Parker Meggitt iPRESS | One wireless pressure sensor per wheel and an aircraft-OEM-configured mobile app. [Parker Meggitt iPRESS](https://www.meggitt.com/insights/wireless-tyre-pressure-system-wtps/) | Tire pressure for every wheel on a phone/tablet without accessing the valve. [Parker Meggitt iPRESS](https://www.meggitt.com/insights/wireless-tyre-pressure-system-wtps/) | A retrofit sensor path can coexist with manual ingestion. |
| Crane SmartStem | Wheel pressure, handheld digital reading, tire/equipment identity, and electronic records. [Crane SmartStem brochure](https://www.craneae.com/sites/default/files/documents/SmartstemCommercial.pdf) | Pressure checking without gas loss, electronic trending, leaking-tire identification, and standardized fleet pressure management. [Crane SmartStem brochure](https://www.craneae.com/sites/default/files/documents/SmartstemCommercial.pdf) | Leak-rate alerts and audit history are practical first forecasting features. |
| Michelin Aircraft Tire app | User-selected fitment/product and maintenance reference content. [Michelin Aircraft Tire app](https://apps.apple.com/us/app/michelin-aircraft-tire/id641618298) | Fitment guide, tire wear guide, product data, and access to the care/service manual. [Michelin Aircraft Tire app](https://apps.apple.com/us/app/michelin-aircraft-tire/id641618298) | Put approved guidance beside the forecast rather than making users search separate manuals. |

### Broader aircraft-health platforms

| Platform | Inputs | Outputs/capabilities | Relevance to a tire product |
| --- | --- | --- | --- |
| Boeing Airplane Health Management | Real-time aircraft data, full-flight data, global fleet data, airline maintenance records, component removals, log entries, and aircraft messages. [Boeing predictive-maintenance overview, pp. 7 and 18](https://services.boeing.com/bgsmedias/sys_master/root/hc6/h1b/8897529937950/C129-Predictive-Maintenance-Ecosystem-Overview-Stephen-Miller-and-Alex-Leung.pdf) | Prognostic, diagnostic, operational, servicing, and performance alerts; servicing examples explicitly include tire-pressure alerts. [Boeing overview, p. 12](https://services.boeing.com/bgsmedias/sys_master/root/hc6/h1b/8897529937950/C129-Predictive-Maintenance-Ecosystem-Overview-Stephen-Miller-and-Alex-Leung.pdf) | Alerts should connect condition, history, procedural guidance, and maintenance action—not stop at a score. |
| Airbus Skywise Core / Fleet Performance+ | In-flight, engineering, operational, aircraft, and airline IT data. [Airbus Skywise Core](https://www.aircraft.airbus.com/en/services/enhance/skywise-data-platform/skywise-core-x) | Health monitoring, predictive maintenance, reliability analysis, real-time event handling, and longer-term maintenance planning. [Airbus Skywise Core](https://www.aircraft.airbus.com/en/services/enhance/skywise-data-platform/skywise-core-x) | Design ingestion as a platform with modular data connectors and multiple time horizons. |
| Airbus Skywise Health Monitoring | Live diagnostic/ACMS feeds, ACARS, alerts, flight-deck effects, maintenance messages, logbook/MIS history, and troubleshooting procedures. [Airbus SHM](https://www.aircraft.airbus.com/en/newsroom/press-releases/2019-04-airbus-launches-skywise-health-monitoring-with-us-airline-allegiant-air-as-early-adopter) | Prioritized/correlated fault cases, operational impact, maintenance history, troubleshooting context, and preparation of tools/parts before arrival. [Airbus SHM](https://www.aircraft.airbus.com/en/newsroom/press-releases/2019-04-airbus-launches-skywise-health-monitoring-with-us-airline-allegiant-air-as-early-adopter) | A tire alert should show evidence, operational impact, applicable procedure, parts availability, and recommended inspection window. |
| Lufthansa Technik AVIATAR | Live aircraft/system/component data; flight-leg/OOOI data; ACMS reports; fault messages; manuals; maintenance records; and M&E integrations such as AMOS and TRAX. [AVIATAR Condition Monitoring](https://www.aviatar.com/en/condition-monitoring) | Current fleet state, trend/failure recognition, proactive recommendations, alerts, troubleshooting, and conversion of unscheduled work into planned maintenance. [AVIATAR Predictive Health Analytics](https://www.aviatar.com/en/predictive-health-analytics) | Airline-specific tuning and integration into existing Tech Ops workflow are core product capabilities. |
| Collins Ascentia | Technician, pilot, sensor, full-flight, maintenance-log, operational, physics-based, statistical, and ML data. [Collins Ascentia](https://www.rtx.com/collinsaerospace/what-we-do/industries/commercial-aviation/analytics-solutions/ascentia-analytics-services), [Collins FlightSense](https://www.rtx.com/collinsaerospace/what-we-do/industries/commercial-aviation/service-solutions/flightsense) | Repeat-event analysis, AOG workflow, custom prognostics, alerts, visualizations, and recommendations; Collins also describes a predictive brake-wear analytic based on operational data where direct sensors are absent. [Collins Power to Predict](https://www.rtx.com/collinsaerospace/what-we-do/industries/air-traffic-management/connected-ecosystem/power-to-predict/) | Use hybrid physics/statistics/ML, support no-code thresholding, and learn from maintenance outcomes. |

### Adjacent tire technology worth borrowing carefully

Michelin's non-aircraft SmartWear/SmartLeak work demonstrates continuous tread estimation, end-of-life
prediction, slow-leak detection, time-to-critical estimates, and confidence-building through data fusion;
it is useful as a product pattern but is not evidence that the same algorithm is valid for aircraft tires.
[Michelin tire digital twin](https://www.michelin.com/en/media/magazine/michelin-innovative-connected-solutions)

Mobile/laser tire-inspection products demonstrate guided image capture, depth measurement, wear-pattern
detection, digital reports, and SDK integration. Aircraft use would require aircraft-specific training data,
measurement-system analysis, qualified procedures, and human confirmation rather than direct reuse of
automotive thresholds. [Zebra Tread Intel](https://www.zebra.com/us/en/software/mobile-computer-software/zebra-tread-intel.html), [Anyline Digital Tire Inspection](https://anyline.com/products/tire-inspection)

## 5. Recommended website use cases

### Personas

- **Line maintenance technician:** capture pressure, tread, images, and defects; see the applicable
  procedure and whether immediate qualified inspection is required.
- **Maintenance Control Center:** prioritize active alerts, aircraft ground time, parts, labor, and the
  next suitable maintenance opportunity.
- **Reliability engineer:** compare fleets, tire models, airports, routes, retread cohorts, and forecast
  calibration.
- **Inventory planner:** forecast removals and tire demand by station with uncertainty bands.
- **Engineering/model owner:** approve source limits, monitor model drift, review false/missed alerts,
  and publish controlled model versions.
- **Read-only auditor:** trace every measurement, prediction, source document, user action, and model
  revision.

### Website pages

| Page | What the user sees | Primary actions |
| --- | --- | --- |
| Fleet overview | Aircraft/tire health map, overdue inspections, pressure anomalies, forecasted removals, and confidence/data-quality badges | Filter by fleet, airport, tire model, status, or maintenance window |
| Aircraft gear view | Diagram of wheel positions with installed tire serials, current measured condition, approved limits, and axle-mate relationships | Open tire, compare mates, record service action |
| Tire digital record | Identity, new/retread history, install/removal timeline, pressure/tread trends, images, defects, accumulated operating exposure, forecasts, and source documents | Add inspection, correct identity, acknowledge alert, create work request |
| Inspection capture | Guided cold/hot pressure context, temperature, calibrated-tool ID, tread measurements by groove/location, controlled defect taxonomy, and required photos | Validate and submit inspection; require human disposition for defects |
| Forecast | Expected wear-out cycles/date with 50/80/95% intervals, threshold-crossing probability, forecast horizon, data completeness, and top drivers | Select planning threshold; compare model against observed history |
| Scenario lab | Baseline schedule versus changed load, route, temperature, taxi, crosswind/yaw, braking, or pressure assumptions | Run Monte Carlo scenarios; compare distributions rather than one number |
| Alerts/work queue | Hard-limit violations, leak trends, inspection due, forecasted threshold crossings, low-confidence warnings, and unresolved data issues | Assign, link procedure, record action/outcome, close with reason |
| Fleet analytics | Removal reasons, cycles by tire model/retread cohort, airport/route effects, pressure-service rate, forecast error, false-alert rate, and demand forecast | Export controlled reports and drill into cohorts |
| Model governance | Model/data version, approved applicability, validation metrics, calibration plots, drift, overrides, rollback, and audit history | Review, approve, deactivate, or roll back a model |

## 6. Required inputs and data model

### A. Asset and approved-limit data

Required before any real forecast:

- Aircraft tail, type/series, landing-gear configuration, exact wheel position, and axle-mate mapping.
- Tire manufacturer, part number, serial/casing ID, size, bias/radial construction, ply rating, speed
  rating, rated load, rated pressure, initial skid/tread depth, manufacture date, new/retread status, and
  retread count. OEM databooks explicitly organize application, speed, pressure, dimension, and gear
  fitment data. [Goodyear DataBook](https://www.goodyearaviation.com/resources/tiredatabook.html)
- Applicable AMM/CMM/ICA limit values, document revision, effective date, approval status, and
  applicability rules.
- Installation/removal time, cycles, station, reason, maintenance release, repair/retread events, and
  prior casing history.

### B. Condition observations

- Pressure value, unit, timestamp, wheel loaded/unloaded, cold/hot state, tire/ambient temperature,
  sensor or gauge ID, calibration status, operator, and measurement method.
- Tread/skid depth by groove and circumferential position, measurement tool, uncertainty, timestamp,
  and operator.
- Controlled defect codes plus dimensions/location/severity for cuts, cracking, chunking, flat spots,
  bulges, separation indications, exposed cords/belts, heat damage, contamination, FOD, and abnormal
  vibration. Manufacturer guidance treats these as distinct removal mechanisms. [Bridgestone examination guide](https://www.bridgestone.com/products/aircraft/eandr/), [Dunlop DM1172](https://www.dunlopaircrafttyres.co.uk/media/1265/dunlop-tcmm-dm1172-issue-11.pdf)
- Standardized images with wheel/tire position, camera/tool metadata, lighting/angle checks, scale
  reference, and human confirmation.

### C. Per-cycle operational exposure

- Flight/cycle ID, timestamps, departure/arrival airport, aircraft weight and CG where approved/available,
  estimated load per wheel, and payload/fuel context.
- Touchdown ground speed, vertical speed or sink-rate proxy, vertical/lateral acceleration, yaw/crab or
  lateral-slip proxy, bounce/hard-landing flags, and wheel spin-up proxy.
- Brake application/energy proxy, brake temperature, anti-skid or locked-wheel events, rejected takeoff,
  and turnaround cooling time.
- Taxi duration, distance, speed distribution, number/severity of tight turns, towing/pushback events,
  and long/high-speed taxi flags.
- Ambient and runway temperature, wind/crosswind, precipitation, runway condition/surface, contamination,
  and known FOD/event reports.

### D. Maintenance outcome labels

- Observed tread change between inspections.
- Pressure loss normalized over time and temperature.
- Removal date/cycles and controlled removal reason: wear-out, pressure loss, FOD, cut, separation,
  flat spot, heat, vibration, scheduled opportunity, unknown, or data error.
- Inspection finding, action taken, parts/labor used, delay/AOG impact, and whether an alert was useful.

Maintenance outcomes are essential because mature platforms explicitly combine sensor/flight data with
log entries, component removals, and alert effectiveness. [Boeing predictive-maintenance overview, pp. 14 and 18](https://services.boeing.com/bgsmedias/sys_master/root/hc6/h1b/8897529937950/C129-Predictive-Maintenance-Ecosystem-Overview-Stephen-Miller-and-Alex-Leung.pdf), [Airbus SHM](https://www.aircraft.airbus.com/en/newsroom/press-releases/2019-04-airbus-launches-skywise-health-monitoring-with-us-airline-allegiant-air-as-early-adopter)

## 7. Recommended outputs

### Hard-rule outputs

- `approved_limit_status`: within limit, approaching limit, limit exceeded, or unknown.
- `required_action_reference`: source document, revision, task/section, and applicability.
- `data_validity`: current, stale, inconsistent, missing, uncalibrated, or out of applicability.
- `inspection_due`: due time and source—not model-created permission.

### Forecast outputs

- Estimated current tread/condition state with measurement timestamp and uncertainty.
- Expected cycles/date to a **planning threshold**, with median and prediction intervals.
- Probability of crossing the planning threshold within 10/25/50/100 cycles or a chosen date.
- Pressure/leak trend and estimated time to a configured inspection threshold.
- Separate probability of unscheduled removal by competing cause, because FOD, pressure loss, heat,
  and defects may remove a tire before normal tread wear-out. FAA identifies FOD as a leading premature
  removal cause. [FAA AC 20-97B](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf)
- Top contributing observations with provenance—not an exposed proprietary equation.
- Confidence grade, forecast horizon, applicability, data completeness, model/data versions, and last
  calibration date.

### Planning outputs

- Recommended **inspection opportunity**, not authorization to continue service.
- Forecast tire demand by station/week with low/base/high quantities.
- Suggested grouping with already-planned maintenance, parts, tools, and qualified personnel.
- Alert priority based on consequence, urgency, confidence, and available ground time.

## 8. Forecasting and simulation approach

### Layer 1: deterministic rules

Implement source-controlled AMM/CMM/ICA pressure, inspection, applicability, and removal rules first.
Rules must fail closed when the tire identity, source revision, or measurement context is missing.

### Layer 2: condition and leak trending

Normalize cold pressure for measurement context, estimate leak rate, compare axle mates, monitor tread
change, and flag inconsistent measurements. Pressure history is already the central value proposition of
PresSense, iPRESS, and SmartStem. [Michelin/Safran PresSense](https://www.michelin.com/en/publications/group/azul-selects-the-pressense-connected-tire-from-safran-and-michelin-to-equip-its-airbus-a320s-and-a321s-and-embraer-195-e12s-and-195-e2s), [Parker Meggitt iPRESS](https://www.meggitt.com/insights/wireless-tyre-pressure-system-wtps/), [Crane SmartStem](https://www.craneae.com/sites/default/files/documents/SmartstemCommercial.pdf)

### Layer 3: calibrated wear-out forecast

Start with an interpretable hierarchical degradation model using measured tread changes and accumulated
exposure. Include tire model, wheel position, retread cohort, aircraft, route/airport, season, and operator
as controlled effects. A point estimate alone is not adequate: aircraft-brake RUL research found that even
apparently simple degradation needs prediction intervals because of stochastic variation. [Oikonomou et al., aircraft-brake RUL](https://research.tudelft.nl/en/publications/remaining-useful-life-prognosis-of-aircraft-brakes/)

### Layer 4: competing-risk model

Model normal wear-out separately from pressure-related removal, FOD/cut, heat/braking damage, flat spot,
separation, and other/unknown removal. Do not train “cycles to removal” as though every removal were the
same physical failure.

### Layer 5: hybrid digital twin

Use physics-informed features for load, spin-up, lateral slip, braking, taxi heat, pressure/deflection, and
temperature, then update the state with inspections. Aircraft-tire digital-twin research has used high-
fidelity test data, Monte Carlo uncertainty, and touchdown variables to predict probability of failure;
broader aircraft research favors hybrid physics/data methods when run-to-failure data are scarce.
[Zakrajsek and Mall](https://scholar.afit.edu/facpub/2057/), [PHM Society hybrid digital twin](https://papers.phmsociety.org/index.php/phmap/article/view/4525)

### Layer 6: scenario simulator

The simulator should accept a planned sequence or distribution of future operations and return a
distribution of possible condition trajectories. It must cap or reject scenarios outside the model's
validated domain and independently flag any approved-limit exceedance.

Example scenario input:

```json
{
  "tire_asset_id": "TIRE-009184",
  "horizon_cycles": 50,
  "planned_operation": {
    "landing_weight_distribution_kg": {"p10": 58000, "p50": 64000, "p90": 70000},
    "touchdown_ground_speed_distribution_ms": {"p10": 62, "p50": 69, "p90": 76},
    "taxi_distance_km": 4.2,
    "taxi_speed_profile": "AIRPORT_ROUTE_PROFILE_7",
    "crosswind_distribution_kt": {"p50": 8, "p90": 18},
    "outside_temperature_distribution_c": {"p10": 18, "p50": 29, "p90": 39},
    "pressure_policy": "MAINTAIN_APPROVED_COLD_TARGET"
  },
  "simulation_runs": 10000
}
```

Example output:

```json
{
  "approved_limits": {
    "status": "WITHIN_DOCUMENTED_LIMITS",
    "source_revision": "CONTROLLED-DOCUMENT-REFERENCE"
  },
  "wear_forecast": {
    "median_cycles_to_planning_threshold": 74,
    "prediction_interval_80_pct": [51, 108],
    "probability_threshold_within_50_cycles": 0.18
  },
  "unscheduled_removal_risk": {
    "horizon_cycles": 50,
    "probability": 0.06,
    "dominant_mode": "PRESSURE_LOSS"
  },
  "recommended_planning_action": {
    "type": "INSPECTION_OPPORTUNITY",
    "within_cycles": 20
  },
  "confidence": "MEDIUM",
  "limitations": [
    "Scenario result is decision support only.",
    "A qualified physical inspection and approved maintenance data remain controlling."
  ]
}
```

The numeric example illustrates an API shape only; it is not a validated aircraft-tire prediction.

## 9. Validation and governance

### Data validation

- Enforce unit, timestamp, tire-position, sensor calibration, source, and plausibility checks.
- Detect tire swaps, serial reuse, impossible tread increases, pressure readings without thermal context,
  duplicate flight cycles, missing axle mates, and late-arriving maintenance events.
- Treat corrected data as append-only revisions with provenance rather than silently overwriting history.

### Model validation

- Split validation by time, aircraft tail, tire casing, and preferably operator/airport; a random row split
  will leak repeated history from the same physical tire.
- Report tread-state error, cycles-to-threshold error, prediction-interval coverage, probability
  calibration, precision/recall, false-alert rate, missed-event rate, and useful warning time. Boeing's
  predictive tooling explicitly evaluates precision, recall, accuracy, and warning time. [Boeing overview, p. 18](https://services.boeing.com/bgsmedias/sys_master/root/hc6/h1b/8897529937950/C129-Predictive-Maintenance-Ecosystem-Overview-Stephen-Miller-and-Alex-Leung.pdf)
- Validate separately by tire model, construction, wheel position, retread cohort, aircraft type, airport,
  climate, and operating regime.
- Backtest proposed maintenance actions, not only numerical predictions: did an alert produce a useful,
  correct action without unnecessary removals?
- Publish the validated applicability envelope and reject or downgrade confidence outside it.

### Safety governance

- A qualified maintainer remains responsible for inspection and disposition.
- Every rule and limit needs controlled source, revision, applicability, approval, and effective dates.
- Every forecast needs model version, data cutoff, confidence, explanation, and reproducibility record.
- Model promotion needs independent technical review, shadow-mode evaluation, rollback, and monitoring.
- Alert design must account for false negatives and false positives, consistent with EASA TPMS guidance.
  [EASA AMC 25.733(f)](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25)
- Do not optimize against catastrophic tire failure as the primary label: failure data are rare and unsafe
  to generate. Aviation-maintenance dataset research explicitly notes the difficulty and ethical problem
  of generating compromised-aircraft examples. [NGAFID maintenance dataset paper](https://arxiv.org/abs/2210.07317)

## 10. Recommended implementation roadmap

### Phase 0 — product foundation

- Tire asset registry and wheel-position history.
- Versioned approved-limit/document registry.
- Manual inspection capture with pressure, thermal context, tread, images, defects, and tool calibration.
- Deterministic rules and audit log.
- Keep the existing wear-severity endpoint explicitly labeled as an unvalidated scenario demonstrator.

### Phase 1 — useful production pilot

- Import flight cycles and maintenance records.
- Pressure/leak and axle-mate trend analytics.
- Tread trend with uncertainty and planning-threshold forecasts.
- Fleet dashboard, work queue, source-linked alerts, and inventory demand forecast.
- Shadow mode only: predictions cannot change approved work intervals.

### Phase 2 — calibrated forecast

- Per-cycle exposure features from QAR/ACMS/airline data.
- Hierarchical wear model and competing-risk removal model.
- Scenario lab with Monte Carlo ranges.
- Airline/MRO feedback loop and model-performance dashboard.

### Phase 3 — advanced sensing and digital twin

- Integrate TPMS/connected pressure hardware.
- Qualified tread/depth capture and aircraft-specific computer vision with human confirmation.
- Hybrid touchdown/taxi thermal model calibrated against dynamometer, rig, and fleet observations.
- Multi-operator validation or privacy-preserving learning only after governance and data agreements.

## 11. Gap analysis against the current API

The current API is appropriate as a hackathon **relative severity calculator**, but it is not a real
remaining-life system.

| Current design | Production gap | Recommended change |
| --- | --- | --- |
| Gear is only `main` or `nose` | No aircraft, tire part number, wheel position, axle mate, serial, construction, or retread history | Introduce aircraft, wheel-position, and tire-asset resources |
| Landing weight stands in for tire load | Actual wheel loads depend on CG, gear geometry, load sharing, and operational reactions. [EASA CS 25.733](https://www.easa.europa.eu/en/document-library/easy-access-rules/online-publications/easy-access-rules-large-aeroplanes-cs-25?page=25) | Use approved load derivation or ingest a validated per-wheel load proxy |
| Crosswind stands in for lateral work | Tire damage relates more directly to yaw/slip/scrub and turning behavior. [Dunlop DM1172](https://www.dunlopaircrafttyres.co.uk/media/1265/dunlop-tcmm-dm1172-issue-11.pdf) | Add yaw/slip, turn, towing, and lateral-acceleration features where available |
| User enters underinflation percentage | No measured pressure, rated target, hot/cold context, temperature, leak history, sensor, or calibration | Store raw observations and derive normalized pressure condition |
| Fixed tread-life assumptions | Skid depth and limits vary with tire/application and approved maintenance data. [Goodyear DataBook](https://www.goodyearaviation.com/resources/tiredatabook.html) | Read versioned tire/aircraft-specific baselines and thresholds |
| One deterministic point result | No uncertainty, applicability, data quality, or model calibration | Return distributions, confidence, versions, and limitations |
| Wear-only estimate | FOD, cuts, pressure loss, heat, flat spots, and separation cause premature removal. [FAA AC 20-97B](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC20-97B.pdf) | Separate wear-out forecast from competing unscheduled-removal risks |
| Stateless request | Real RUL requires longitudinal measurements and outcomes | Add persistent event history, provenance, corrections, and audit trails |

## 12. Research limitations and next evidence needed

- Public sources document pressure monitoring and general aircraft-health platforms well, but detailed
  commercial aircraft-tire RUL algorithms and their fleet accuracy are proprietary.
- No authoritative public, representative commercial-aircraft tire run-to-removal dataset was identified
  in this review. Published aircraft-tire digital-twin work references high-fidelity testing rather than a
  broadly reusable airline dataset. [Zakrajsek and Mall](https://scholar.afit.edu/facpub/2057/)
- OEM manuals give general practices, but exact dispatch/removal limits must come from controlled
  aircraft/operator documents for the selected fleet.
- Before model development, secure a data partnership with an airline, MRO, tire OEM, or landing-system
  OEM and obtain at least tire identity/history, repeated condition measurements, per-cycle exposure, and
  controlled removal reasons.
- The first pilot should target a single aircraft family, tire model, wheel position group, and operator;
  broad cross-fleet support before calibration would create unjustified confidence.

## Recommended product statement

> The platform tracks each aircraft tire's measured condition and operating exposure, applies controlled
> maintenance limits, forecasts planning thresholds with uncertainty, and simulates future operating
> scenarios. It supports qualified maintenance planning and does not replace physical inspection,
> approved maintenance data, or authorized airworthiness decisions.
