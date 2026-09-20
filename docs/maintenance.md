# Workstation Maintenance

Each host controls the weekly disk report through `workstation.maintenance.enable`. The
`workstation.maintenance.mole.enable` and `workstation.maintenance.dockerPrune.enable` options
independently permit destructive cleanup after the configured disk-usage threshold. Both options
default to disabled; both current hosts explicitly enable them.

`WEEKLY_DISK_DRY_RUN` may be unset, `0`, or `1`. Setting it to `1` logs cleanup commands without
executing them. Any other value, including an explicitly empty value, aborts before creating the
log directory or attempting cleanup.

LaunchAgent maintenance must remain least-destructive by default. Running Docker cleanup or the
maintenance script outside dry-run mode requires explicit approval because it may delete images,
containers, caches, or user data.

Home Manager backup cleanup is separately exposed through:

```sh
make home-manager-backups-cleanup
make home-manager-backups-cleanup KEEP_DAYS=90
make home-manager-backups-cleanup CONFIRM=1
```

The default invocation only lists candidates. Deletion requires `CONFIRM=1`.
