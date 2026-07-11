# Aircraft-tire model governance

## Current release status

The active release is `pilot-sim-2.0.0`. Its manifest deliberately records:

| Control | Current value |
|---|---|
| Lifecycle | `DEVELOPMENT` |
| Permitted use | `SCENARIO_PLANNING` |
| Exact aircraft/tire target | Not assigned |
| Calibration | `NOT_PERFORMED` |
| Validation | `NOT_PERFORMED` |
| Operational authorization | `NOT_AUTHORIZED` |

This means the API can support bounded what-if exploration. It cannot support maintenance planning,
dispatch, serviceability, removal, or airworthiness decisions. Requests for
`MAINTENANCE_PLANNING` or `DISPATCH_SUPPORT` fail closed with HTTP `409` and no numeric forecast.
Operational output also has an independent hard gate: even a future evidence-authorized release is
blocked until the deployment resolves pressure and service limits from a controlled installation
configuration instead of accepting them as caller-controlled assumptions.

## Lifecycle gates

Releases progress only when the evidence manifest satisfies every preceding gate:

1. `DEVELOPMENT`: calibration, validation, and authorization evidence must all be absent. Runtime
   evaluation can permit a declared scenario-planning use, but never an operational use.
2. `CALIBRATED_SHADOW`: an exact target's canonical training partition, predeclared policy, frozen
   predictions, and calibration report pass semantic verification against the parameter and
   implementation bytes. No operational authorization.
3. `VALIDATED_SHADOW`: calibration passed and a disjoint whole-casing holdout partition passed a
   predeclared target-specific claim evaluator and accountable acceptance decision. Validation is
   explicitly scoped by claim; no operational authorization.
4. `AUTHORIZED`: every modeled output claim required for operational use is separately validated,
   and controlled documents, named approver, effective period, and permitted uses are present.
5. `SUSPENDED` or `RETIRED`: the release is unavailable for new assessments regardless of earlier
   evidence.

The contract will not accept calibration or validation without an exact target identity, will not
accept validation without calibration, and will not accept the same partition digest for training
and holdout. Both partitions must bind the same source snapshot and frozen split while remaining
disjoint by casing and record. Authorization cannot grant a use that the release did not declare.

A different digest alone proves only byte inequality. The canonical partition artifacts embed their
rows and membership, allowing the loader to cross-check source/split identity and casing/record
disjointness. Time, aircraft-tail, operator, airport, and future-information leakage still require a
predeclared study design and independent review. A `REAL_FLEET` label and reviewer fields record
claims; operator provenance, source attestation, signer identity, and approver authority remain
external controls that software schemas cannot establish by themselves.

## Evidence and artifact integrity

Each release is a directory under `app/model_releases` containing a strict manifest, typed parameter
artifact, optional supporting research evidence, and any claimed promotion artifacts. At load time
the registry:

- rejects unknown manifest fields and coerced values;
- rejects path traversal, symlinked release artifacts, and mismatched release identifiers;
- calculates the parameter file's SHA-256 digest and compares it with the manifest;
- verifies every declared supporting-evidence path and SHA-256 digest while preserving its explicit
  source kind, applicability, and permitted research use;
- rejects reuse of a non-target supporting-evidence digest as calibration or holdout data;
- validates the parameter identity, types, ranges, profiles, and cross-field invariants;
- requires parameter calibration status and target identity to match the evidence manifest;
- requires promotion artifacts to use canonical JSON, validates their strict schemas, and verifies
  training/holdout partitions, policies, predictions, reports, and acceptance decisions;
- recomputes the currently supported wear-rate metrics from frozen embedded rows and predictions;
- calculates a SHA-256 digest over the ordered calculation-source paths and bytes declared in the
  manifest, then refuses to load a release when that implementation digest differs;
- loads the verified parameters into frozen runtime models consumed by the calculator and simulator;
- returns the manifest, parameter, implementation, and supporting-evidence identities and digests in the API's
  `governance` section.

The parameter checksum detects a changed or corrupted parameter artifact. Supporting-evidence
checksums detect changed or substituted research artifacts but do not make non-target evidence
applicable. Promotion-artifact digests and semantic cross-checks prevent a manifest-only `PASS` or a
report-only metric substitution. The implementation checksum now covers calculation, safety,
governance, calibration, validation, and public contract sources declared by the release. The
manifest digest identifies the exact manifest bytes. These controls provide reproducibility and
tamper detection; they do not authenticate an operator source, prove statistical adequacy, confer
OEM/FAA approval, or establish approver authority.

The current evaluator supports only `TREAD_WEAR_RATE_POINT`. The operational gate requires separate
validation of severity classification, tread interval coverage, cycles-to-threshold, threshold-event
probability, pressure-policy counterfactual, recommendation policy, temporal generalization, and
aircraft-tail generalization. Consequently the present verifier cannot load an operationally
authorized release from one wear-rate report, by design.

Result reproduction requires the exact request, random seed, release artifacts, dependencies, and
runtime environment. The implementation digest covers only the source paths declared by the
manifest, not the Python interpreter, third-party dependencies, or complete container. Deployments
must therefore retain the Git revision or container-image digest alongside assessment records. CI
must continue to prove that each model coefficient, profile, and modeled input domain is sourced
from the typed, checksum-verified parameter artifact. Separate fail-closed safety-policy constants
must remain implementation-digest covered and, before operational use, be replaced or supported by
controlled installation data.

## Public-reference target

The first research target is a Boeing 737-800 main-gear installation using the Bridgestone
APR04450, size H44.5 x 16.5R21. It is documented in
[`validation-target-b737-800-apr04450.md`](validation-target-b737-800-apr04450.md).

That target remains `PUBLIC_REFERENCE_TARGET_ONLY`. The
[Bridgestone application and specification tables](https://www.bridgestone.com/products/aircraft/products/applications/pdf/BS_AC_Manual_2022_P.102-109.pdf)
are useful for defining identity and test bounds, but they are not operator maintenance
instructions; the [FAA also states that a TSO authorization is not installation
approval](https://www.faa.gov/aircraft/air_cert/design_approvals/tso). The published 230 psi value is
an unloaded reference, and the published 0.51-inch tread depth is new-tire geometry, not a removal
limit. Current controlled Boeing and operator documents must establish applicability, service
pressure, inspection rules, and approved limits before the target can enter an operational
authorization package.

The active generic pilot profile's 10.9 mm initial tread-depth boundary is not an APR04450 value and
must not be substituted for the published 12.95 mm new-tire geometry. A target-specific release must
derive its modeled range from target-specific calibration evidence and controlled installation data.

## Promotion using real fleet data

Promotion is an evidence-producing process, not a manifest edit performed in isolation:

1. Freeze a source extract that meets the record contract in
   [`fleet-calibration-data-contract.md`](fleet-calibration-data-contract.md), retain provenance,
   and calculate its SHA-256 digest.
2. Audit identity, gauge calibration, feature completeness, outcomes, and minimum sample readiness.
   Split by whole casing and freeze canonical training/holdout artifacts so measurements from one
   physical casing cannot leak across the boundary.
3. Predeclare target-specific metrics and acceptance thresholds before fitting. The current project
   minima are data-readiness gates only; they are not statistical acceptance criteria.
4. Fit on the training casings using a separately reviewed, reproducible fitting implementation.
   Freeze its per-record predictions and produce a parameter artifact and calibration report tied to
   the exact partition, policy, and implementation digest.
5. Lock the model, then evaluate once on the distinct holdout casings. Record metrics,
   uncertainty, operational envelope, subgroup results, failure analysis, and the signed acceptance
   decision. The implemented evaluator enforces exact target and wheel-position identity,
   one-to-one interval predictions, no training/holdout casing overlap, and explicit MAE, RMSE, bias,
   and p90-error limits. That evaluator proves only the point wear-rate claim; passing it is necessary
   but insufficient for any broader forecast or operational claim.
6. Create a new immutable release manifest with exact aircraft/tire identity and the dataset/report
   digests. Advance only to `CALIBRATED_SHADOW` or `VALIDATED_SHADOW` according to the evidence
   actually available.
7. Run in shadow mode, monitor drift and data quality, and define suspension triggers. Shadow
   performance does not itself authorize operational use.
8. For operational use, obtain controlled aircraft/operator maintenance references and a documented
   approval by the accountable organization. Record its scope, permitted uses, effective time, and
   expiry in a new `AUTHORIZED` release.
9. Implement and independently verify a controlled installation resolver keyed by exact aircraft,
   tire, wheel position, and applicable document revision. It must supply pressure, inspection, and
   service limits server-side and reject caller overrides. Authorization metadata alone does not
   bypass this runtime gate.

Every promotion should create a new release identifier. Existing release contents and evidence
digests must remain unchanged. Historical result reproduction additionally requires the retained
request, random seed, dependency lock, and deployed container-image or source revision.

The repository currently implements evidence loading, readiness checks, partition freezing,
prediction/report binding, and metric recomputation. It does not yet implement a statistically
selected fitting algorithm for APR04450 fleet records. That algorithm and its methodology must be
chosen only after authentic target data, measurement protocol, and predeclared study design exist.

## Runtime safety behavior

Even a permitted scenario request is withheld when the tire has a known defect, has reached the
configured planning threshold, or has a 10% pressure deficit. A missing, malformed, or
checksum-invalid evidence package returns HTTP `503`. Schema-valid inputs outside the release's
modeled envelope return HTTP `422` rather than being extrapolated. Operational output remains
disabled without a controlled installation resolver, even if the release evidence would otherwise
permit the requested use. These gates prevent the API from producing a plausible-looking forecast
when inspection, controlled maintenance data, or evidence integrity must take precedence.

Fail-closed behavior is a necessary safety control, but it is not a substitute for aircraft-level
system safety assessment, independent verification, human factors review, controlled maintenance
data, operational approval, or continued-airworthiness monitoring.
