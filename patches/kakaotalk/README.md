# Automatic KakaoTalk patching

`darwin-rebuild switch` runs `kakaotalk-activate` as root in nix-darwin's
`postActivation`, after App Store (`mas`) installation and the Homebrew bundle.
It patches a private copy, then atomically exchanges it with
`/Applications/KakaoTalk.app` when the installed app is supported and not running.
The Dock and LaunchServices keep using that same path; no second discoverable
app bundle or alias is installed. Missing apps are skipped; running, unsupported,
or unsafe inputs warn and skip without failing ordinary activation.
The command never quits or launches KakaoTalk; close it before switching.

The private, root-owned transaction state and verified original backups are kept
under `/Library/Application Support/nix-kakaotalk`. Failed staging leaves the
installed original alone; failed post-publish verification exchanges it back.
Old backups are retained, including after App Store updates; supported new
originals are patched on the next switch. The same original and package are a
verified no-op. Unknown/already-patched inputs or a different patcher identity
are not re-patched: roll back explicitly before migrating. Roll back with:

```sh
sudo kakaotalk-activate --rollback
```

Rollback restores the recorded original only when the installed app still
matches the recorded patch. The journal remains, so the next switch reapplies
the patch. `kakaotalk-patcher` remains available as a copy-only tool; normal
operation is switch-managed.

Only `com.kakao.KakaoTalkMac` 26.9.0 build 2006, universal x86_64/arm64, with
original `Contents/MacOS/KakaoTalk` SHA-256
`456e1a3ed7a87168888bdb8c6e4894764a028e62c0af68562a760d9909d2bb65` is
supported. Unknown inputs fail closed. Patching verifies the original app,
preserves entitlements, verifies the new signature and unchanged resources,
and keeps app bundles out of the Nix store. Ad-hoc signing is not notarization;
macOS trust, privacy prompts, and application runtime behavior require separate
verification.
