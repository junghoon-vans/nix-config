{ runCommand, source }:

runCommand "paseo-exporter" { } ''
  cp -R ${source} "$out"
  chmod -R u+w "$out"

  # Schema defaults cover RPC callers; factory defaults cover the export UI.
  substituteInPlace "$out/shared/export.ts" \
    --replace-fail 'includeReasoning: z.boolean().default(true)' 'includeReasoning: z.boolean().default(false)' \
    --replace-fail 'includeTools: z.boolean().default(true)' 'includeTools: z.boolean().default(false)'
  substituteInPlace "$out/shared/preferences.ts" \
    --replace-fail 'includeReasoning: true, includeTools: true' 'includeReasoning: false, includeTools: false' \
    --replace-fail 'destination: "exports", directory: ""' 'destination: "custom", directory: "~/.local/share/paseo/exports"'
''
