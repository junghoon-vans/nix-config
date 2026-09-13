.DEFAULT_GOAL := help

.PHONY: help bootstrap switch

help:
	@printf '%s\n' \
	  'make bootstrap HOST=<host>  Bootstrap and activate a host configuration' \
	  'make switch HOST=<host>     Activate an installed host configuration'

bootstrap:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make bootstrap HOST=junghoonui-MacBookAir' >&2; exit 2; }
	./scripts/nix/bootstrap.sh "$(HOST)" "$(CURDIR)"

switch:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make switch HOST=junghoonui-MacBookAir' >&2; exit 2; }
	sudo -H darwin-rebuild switch --flake .#$(HOST)
