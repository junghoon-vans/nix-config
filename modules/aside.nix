{ lib, pkgs, ... }:

let
  model = modelId: thinkingLevel: {
    provider = "openai-codex";
    inherit modelId thinkingLevel;
    fastMode = false;
  };
  settings = pkgs.writeText "aside-managed-settings.json" (
    builtins.toJSON {
      defaultModel = model "gpt-5.6-luna" "high";
      modelCategories = {
        standard = model "gpt-5.6-luna" "medium";
        deep = model "gpt-5.6-sol" "medium";
        visual = model "gpt-5.6-terra" "high";
      };
      imageGenerationModel = null;
      permission = {
        rules.default = "ask";
        sandbox.enabled = true;
        files = {
          outsideRead = "ask";
          outsideWrite = "ask";
        };
      };
      contextAwareness = {
        enabled = false;
        captureTypedText = false;
        screenOcr = false;
      };
      analytics.enabled = false;
      routineSuggestions.enabled = false;
      memory = {
        enabled = true;
        episodicRetentionDays = 30;
      };
      paymentUse.enabled = false;
      communication.enabled = false;
    }
  );
  applySettings = pkgs.writeShellApplication {
    name = "apply-aside-settings";
    text = ''
      exec ${pkgs.python3}/bin/python3 ${../scripts/aside/apply-settings.py} ${settings} "$@"
    '';
  };
in
{
  home.packages = [ applySettings ];

  home.activation.applyAsideSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${lib.getExe applySettings} --activation
  '';
}
