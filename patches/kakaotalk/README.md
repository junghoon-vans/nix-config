# KakaoTalk patch research

Status: **research-only, not applied, not locally verified**. No patch, patcher,
original executable, or modified application is included. This record is not a Nix
package or an installation instruction; follow the [collection policy](../README.md)
before adding any implementation.

## Candidate from prior discussion

- Source: <https://github.com/betive37/mac-kakaotalk-adblock/tree/5eb55199f3aa0c9680b8d080c7d5221a4725d627>.
- Reported target: macOS KakaoTalk `26.9.0`, build `2006`, universal arm64/x86_64.
- Reported original executable SHA-256:
  `456e1a3ed7a87168888bdb8c6e4894764a028e62c0af68562a760d9909d2bb65`.
  This value is carried over from the discussion, not measured against a local app;
  it is not an installer/archive hash or a patch hash.
- Reported approach: inspect and patch both Mach-O architecture slices, preserve
  entitlements, then ad-hoc re-sign. This is a binary patching workflow, not an
  ordinary `stdenv` source patch.
- Patch/patcher integrity hash: not recorded; no implementation has been imported.
- Patch author/license and redistribution permission: not independently reviewed.
  The repository's license must not be assumed to cover this third-party material
  or the proprietary target application. Do not vendor it until reviewed.
- Validation: no local applicability, build, signing, arm64/x86_64, or runtime checks
  performed. The source's behavior and compatibility remain unverified here.

Before implementation, independently inspect the pinned source and license, verify
that the version/build and executable hash match the actual input, and record real
architecture, signing/entitlements, build and runtime results. Any version, build or
input-hash change requires a fresh review; do not carry offsets forward blindly.
Retire this candidate if upstream resolves the need, the target becomes incompatible,
or provenance/license cannot be verified.

No application installation/modification, Nix wiring or activation, hosts/certificate
changes, or signing operations are enabled by this record.
