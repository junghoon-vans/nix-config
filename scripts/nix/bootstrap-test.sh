#!/usr/bin/env bash

set -euo pipefail

script_dir="$(dirname "${BASH_SOURCE[0]}")"
cd "$script_dir/../.."
repository_root="$PWD"
bootstrap_script="$repository_root/scripts/nix/bootstrap.sh"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/nix-bootstrap-test.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT

stub_bin="$test_root/bin"
test_home="$test_root/home"
mkdir -p "$stub_bin" "$test_home"

cat >"$stub_bin/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

: "${BOOTSTRAP_SUDO_LOG:?BOOTSTRAP_SUDO_LOG must be set}"
printf '%s\n' "$*" >>"$BOOTSTRAP_SUDO_LOG"

if [[ "${1:-}" == "/bin/cp" ]]; then
    shift
    [[ "$#" -eq 2 && "$2" == "$NIX_CONF" && "$2" == "$HOME/"* ]] || exit 97
    exec /bin/cp "$@"
fi
if [[ "${1:-}" == "-H" && "${2:-}" == "nix" ]]; then
    shift 2
    exec nix "$@"
fi

printf 'unexpected sudo invocation\n' >&2
exit 97
EOF

cat >"$stub_bin/nix" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

: "${BOOTSTRAP_NIX_LOG:?BOOTSTRAP_NIX_LOG must be set}"
printf '%s\n' "$*" >>"$BOOTSTRAP_NIX_LOG"
exit "${BOOTSTRAP_NIX_STATUS:-1}"
EOF

chmod +x "$stub_bin/sudo" "$stub_bin/nix"

fail() {
    printf 'bootstrap regression failed: %s\n' "$*" >&2
    exit 1
}

assert_file_contains() {
    local file="$1"
    local expected="$2"

    if ! grep -F -- "$expected" "$file" >/dev/null; then
        fail "$file does not contain: $expected"
    fi
}

missing_host_conf="$test_home/missing-host.conf"
missing_host_sudo_log="$test_root/missing-host-sudo.log"
missing_host_nix_log="$test_root/missing-host-nix.log"
missing_host_output="$test_root/missing-host.output"
printf '%s\n' sentinel >"$missing_host_conf"

if env \
    HOME="$test_home" \
    PATH="$stub_bin:/usr/bin:/bin" \
    NIX_CONF="$missing_host_conf" \
    BOOTSTRAP_SUDO_LOG="$missing_host_sudo_log" \
    BOOTSTRAP_NIX_LOG="$missing_host_nix_log" \
    "$bootstrap_script" >"$missing_host_output" 2>&1; then
    fail 'missing host unexpectedly succeeded'
fi
if [[ -e "$missing_host_sudo_log" || -e "$missing_host_nix_log" ]]; then
    fail 'missing host invoked a privileged or Nix stub'
fi
missing_host_contents="$(<"$missing_host_conf")"
if [[ "$missing_host_contents" != sentinel ]]; then
    fail 'missing host changed its Nix configuration'
fi

activation_conf="$test_home/activation.conf"
activation_sudo_log="$test_root/activation-sudo.log"
activation_nix_log="$test_root/activation-nix.log"
activation_output="$test_root/activation.output"
printf '%s\n' '# preserve this setting' 'experimental-features = nix-command' >"$activation_conf"

if env \
    HOME="$test_home" \
    PATH="$stub_bin:/usr/bin:/bin" \
    NIX_CONF="$activation_conf" \
    BOOTSTRAP_SUDO_LOG="$activation_sudo_log" \
    BOOTSTRAP_NIX_LOG="$activation_nix_log" \
    BOOTSTRAP_NIX_STATUS=42 \
    "$bootstrap_script" test-host "$repository_root" >"$activation_output" 2>&1; then
    fail 'Nix activation failure unexpectedly succeeded'
else
    status=$?
fi
if [[ "$status" -ne 42 ]]; then
    fail "Nix activation failure returned $status instead of 42"
fi
assert_file_contains "$activation_conf" 'experimental-features = nix-command flakes'
assert_file_contains "$activation_conf" '# preserve this setting'

printf 'bootstrap failure-path checks passed.\n'
