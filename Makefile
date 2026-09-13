.DEFAULT_GOAL := help

.PHONY: help bootstrap switch setup-apm

help:
	@printf '%s\n' \
	  'make bootstrap HOST=<host>  Bootstrap and activate a host configuration' \
	  'make switch HOST=<host>     Activate an installed host configuration' \
	  'make setup-apm              Deploy the locked APM agent skills'

bootstrap:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make bootstrap HOST=junghoonui-MacBookAir' >&2; exit 2; }
	./scripts/nix/bootstrap.sh "$(HOST)" "$(CURDIR)"

setup-apm:
	./scripts/apm/setup-apm.sh "$(CURDIR)"

switch:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make switch HOST=junghoonui-MacBookAir' >&2; exit 2; }
	sudo -H darwin-rebuild switch --flake .#$(HOST)
