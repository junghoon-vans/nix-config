# KakaoTalk copy patcher

```sh
nix run .#kakaotalk-patcher -- --source /path/to/KakaoTalk.app --output "$HOME/kakaotalk-patched"
```

The output directory must not exist; its parent must exist. Only the new
`kakaotalk-patched/KakaoTalk.app` is patched and ad-hoc signed. Nothing is installed,
launched, or activated. Keep the original app; delete the output directory to discard
the patched copy. Output under `Applications`, another app, or `/nix/store` is refused.

Supports only `com.kakao.KakaoTalkMac` 26.9.0 build 2006, universal x86_64/arm64,
original `Contents/MacOS/KakaoTalk` SHA-256
`456e1a3ed7a87168888bdb8c6e4894764a028e62c0af68562a760d9909d2bb65`.
Unknown inputs fail closed. The tool checks the original signature, preserves
entitlements, verifies the new signature and unchanged resources, and leaves the
source untouched. Ad-hoc signing is not notarization; application runtime and
macOS trust/privacy behavior require separate verification.

`packages/kakaotalk-patcher.nix` hash-pins the MIT-licensed patch primitives from
[betive37/mac-kakaotalk-adblock at 5eb5519](https://github.com/betive37/mac-kakaotalk-adblock/tree/5eb55199f3aa0c9680b8d080c7d5221a4725d627)
and installs its original MIT notice. `patch_copy.py` is the only packaged entrypoint;
upstream's installed-app installer is not included. No proprietary app enters the
Nix store or package closure. Do not commit or upload original/patched bundles.
