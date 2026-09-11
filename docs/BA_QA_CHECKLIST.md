# BA / QA Checklist — Facebook Story Automation Android

Status vocabulary:

- **PASS**: reviewed and implemented.
- **AUTOMATED**: covered by CI/unit tests.
- **PILOT-PENDING**: requires the real Android device / Meta UI.
- **PRODUCTION-BLOCKED**: must be closed before enabling autonomous publish.

## 1. Authentication and account safety

| Scenario | Expected behavior | Status |
|---|---|---|
| Railway attempts to use Facebook browser/session | Impossible; runtime contains no Meta browser transport | PASS |
| Meta password/2FA/cookie leaves phone | Never sent to backend | PASS |
| Android API token missing/short | Backend/app refuses to run | PASS / AUTOMATED |
| API token stored on phone | Android Keystore, not normal SharedPreferences | PASS |
| Upgrade from v0.1 plaintext token | Old plaintext keys are scrubbed | PASS |
| HTTP backend configured | App backend is fixed HTTPS and cleartext is disabled | PASS |
| Accessibility listens to another app | Events ignored; package restricted to Meta Business Suite | PASS |

## 2. Queue and business rules

| Scenario | Expected behavior | Status |
|---|---|---|
| Blank JOB_ID | Generate stable `AUTO-...-R<row>` and persist | PASS / AUTOMATED |
| Duplicate JOB_ID | Fail safely; no Android handoff | PASS |
| Missing schedule | Android API rejects handoff | PASS |
| Future schedule | Not returned by `/next` | PASS |
| Missing fixed URL | Preparation fails | PASS |
| Link differs while locked | Reject with `LINK_LOCKED_MISMATCH` | PASS |
| Missing Link Text pool | Preparation fails | PASS |
| Invalid content type | Preparation fails/review required | PASS |
| Retry not due yet | `/next` and `/claim` do not bypass gate | PASS |
| Published Story appears again | Terminal/idempotent; must not re-run | PASS / AUTOMATED |

## 3. Claim / lease / concurrency

| Scenario | Expected behavior | Status |
|---|---|---|
| Device A claims job | `PROCESSING` + per-job claim token + lease | PASS / AUTOMATED |
| Device A repeats claim after lost response | Same active claim returned idempotently | PASS |
| Device B claims active job | 409 `JOB_CLAIMED_BY_OTHER_DEVICE` | PASS |
| Lease expires | Media/result rejected; server recovery accounts retry | PASS / AUTOMATED |
| Old v0.1 PROCESSING row has no claim | Recover as legacy stale claim | PASS |
| Release fails over network | Phone retains local job for recovery | PASS |
| Result response lost after server wrote state | Repeated callback returns idempotent success | PASS |
| Multiple Railway replicas | Current process lock is insufficient across replicas | PRODUCTION-BLOCKED |

## 4. Media safety

| Scenario | Expected behavior | Status |
|---|---|---|
| Ready file is empty | Reject | PASS |
| Ready file exceeds max size | Reject | PASS |
| Ready file MIME is not image/video | Reject | PASS |
| Ready file not in approved Drive folder | Reject | PASS |
| Temporary API media file | Random path and deleted after response | PASS |
| Download filename contains unsafe chars | Sanitize | PASS |
| Corrupt/forged file with misleading extension | Deep magic/codec validation not complete | PRODUCTION-BLOCKED |
| Arbitrary source video codec | Full H.264/AAC normalization not guaranteed | PRODUCTION-BLOCKED |
| Arbitrary image dimensions | Full 9:16 normalization without music not guaranteed | PRODUCTION-BLOCKED |

## 5. Android lifecycle

| Scenario | Expected behavior | Status |
|---|---|---|
| User double-taps Pilot | Process-wide gate prevents double launch | PASS |
| Activity rotates/recreates during pilot start | Same process gate prevents a second claim | PASS |
| App/process dies after claim | Lease eventually expires and server recovers job | PASS |
| App dies before claim persisted locally | Same-device claim retry is idempotent; server lease recovery exists | PASS |
| Continuous foreground polling | Removed from Pilot | PASS |
| Autonomous exact-time scheduling | Not implemented yet | PRODUCTION-BLOCKED |

## 6. Accessibility fail-safe

| Scenario | Expected behavior | Status |
|---|---|---|
| Exact one `Tạo tin/Create story` match | Click | PASS / AUTOMATED matcher |
| No matching Create Story | Stop and save diagnostic | PASS |
| More than one matching Create Story | Stop; no click | PASS |
| `Đăng` appears inside `Đăng nhập` | Must NOT match | AUTOMATED |
| `Link` appears inside `Copy link` | Must NOT match | AUTOMATED |
| Exact one Photo/Video match | Click | PASS |
| Meta-internal media picker reached | Stop and report dry-run diagnostic | PASS |
| Android launches a system/gallery picker in another package | Do not broaden Accessibility; no action in foreign package, then recover/release job for device-specific mapping | PILOT-PENDING |
| Editable URL/email appears in diagnostic | Editable omitted; URL/email redacted | PASS |
| Unknown automation stage | Stop; no UI action | PASS |
| Media thumbnail selection | Not present in Pilot APK | PILOT-PENDING |
| Link Sticker handling | Not present in Pilot APK | PILOT-PENDING |
| Publish click | Not present in Pilot APK | PRODUCTION-BLOCKED |

## 7. Server safety switches

Pilot app must refuse to run unless `/api/android/ping` simultaneously reports:

- `ok=true`
- `transport=ANDROID`
- `dry_run=true`
- `pilot_safe_mode=true`

Changing only one switch is not enough to enable posting. Production activation will require a separately reviewed app/version and explicit user approval.

## 8. Automated CI gates

Backend:

- Python compile
- API authorization/safety guards
- state-machine negative tests
- claim/lease tests
- dry-run Publish rejection
- marker parsing/injection tests
- number locale regression
- stable JOB_ID tests
- link text/music existing tests

Android:

- exact UI matcher unit tests
- Android lint
- debug APK build

No APK is considered testable until these gates pass on the source commit used to build it.

## 9. Real-device Pilot acceptance criteria

Before extending automation beyond the media picker, all must pass on the spare Android phone:

1. user can sign in to Meta Business Suite manually without account checkpoint;
2. app safety ping passes;
3. Accessibility is enabled only for MEGAS Story Companion;
4. one controlled test job is claimed once;
5. correct Story creation flow opens;
6. media picker behavior/package is identified without selecting media;
7. if picker remains inside Meta, diagnostic is captured and server receives `ANDROID_DRY_RUN_OK`;
8. if picker is external, app performs no foreign-package action and job is safely recovered/released;
9. queue does not redeliver a completed Pilot job;
10. no Story is published;
11. no Facebook credential/session exists in Railway logs or variables.

## 10. Production blockers

Do not enable auto-publish until all are closed:

1. exact media-picker selection mapped and verified across repeated runs;
2. Link Sticker UI mapped and verified with the fixed recruiting URL;
3. final composer and publish confirmation mapped;
4. autonomous exact-time Android scheduler implemented and tested against Android background restrictions;
5. multiple consecutive real-device dry-runs pass;
6. full media compatibility/normalization completed;
7. distributed claim locking implemented if Railway ever runs more than one replica;
8. production release APK signed and separated from Pilot build;
9. explicit user approval to enable the final Publish action.
