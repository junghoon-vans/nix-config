.DEFAULT_GOAL := help

.PHONY: help check inventory inventory-check bootstrap switch home-manager-backups-cleanup

help:
	@printf '%s\n' \
	  'make check                                      Run the same validation checks as CI' \
	  'make inventory                                  Generate the managed app and tool inventory from Nix' \
	  'make inventory-check                            Check inventory synchronization without writing' \
	  'make bootstrap HOST=<host>                      Bootstrap, activate, and install locked agent skills' \
	  'make switch HOST=<host>                         Activate and install locked agent skills' \
	  'make home-manager-backups-cleanup               List backups older than 30 days' \
	  'make home-manager-backups-cleanup CONFIRM=1     Delete listed backups' \
	  'make home-manager-backups-cleanup KEEP_DAYS=90  Set the retention period'

check:
	nix develop --no-write-lock-file --command ./scripts/validation/check.sh

inventory:
	python3 -B scripts/docs/update-inventory.py

inventory-check:
	python3 -B scripts/docs/update-inventory.py --check

home-manager-backups-cleanup:
	KEEP_DAYS="$(or $(KEEP_DAYS),30)" CONFIRM="$(or $(CONFIRM),0)" ./scripts/nix/home-manager-backups-cleanup.sh

bootstrap:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make bootstrap HOST=junghoonui-MacBookAir' >&2; exit 2; }
	./scripts/nix/bootstrap.sh "$(HOST)" "$(CURDIR)"
	./scripts/apm/setup-apm.sh "$(CURDIR)"

switch:
	@test -n "$(HOST)" || { printf '%s\n' 'Set HOST, for example: make switch HOST=junghoonui-MacBookAir' >&2; exit 2; }
	sudo -H darwin-rebuild switch --flake .#$(HOST)
	./scripts/apm/setup-apm.sh "$(CURDIR)"
