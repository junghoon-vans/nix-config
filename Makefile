.DEFAULT_GOAL := help

.PHONY: help check bootstrap switch

help:
	@printf '%s\n' \
	  'make check                  Run the same validation checks as CI' \
	  'make bootstrap HOST=<host>  Bootstrap, activate, and install locked agent skills' \
	  'make switch HOST=<host>     Activate and install locked agent skills'

check:
	nix develop --no-write-lock-file --command ./scripts/validation/check.sh

bootstrap:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make bootstrap HOST=junghoonui-MacBookAir' >&2; exit 2; }
	./scripts/nix/bootstrap.sh "$(HOST)" "$(CURDIR)"
	./scripts/apm/setup-apm.sh "$(CURDIR)"

switch:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make switch HOST=junghoonui-MacBookAir' >&2; exit 2; }
	sudo -H darwin-rebuild switch --flake .#$(HOST)
	./scripts/apm/setup-apm.sh "$(CURDIR)"
