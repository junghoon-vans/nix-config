import json
from pathlib import Path
import tempfile
import unittest

import paseo_support


SOURCE_TEXTS = {
    "provider-config.ts": '''
      export const OmpProviderOptionsSchema = z
        .object({
          smolModel: z.string().min(1).optional(),
          slowModel: z.string().min(1).optional(),
          planModel: z.string().min(1).optional(),
        })
        .strict();
      function resolveOmpModelRoleArgs(modelRoles) {
        const args = [];
        if (modelRoles.smolModel) args.push("--smol", modelRoles.smolModel);
        if (modelRoles.slowModel) args.push("--slow", modelRoles.slowModel);
        if (modelRoles.planModel) args.push("--plan", modelRoles.planModel);
      }
    ''',
    "map-omp-model.ts": '''
      export function mapOmpModel(model, provider) {
        return {
          provider,
          id: `${model.provider}/${model.id}`,
          metadata: { provider: model.provider, modelId: model.id, },
        };
      }
    ''',
    "cli-runtime.ts": '''
      const DEFAULT_OMP_COMMAND: [string, ...string[]] = [process.env.OMP_COMMAND ?? "omp"];
      async getAvailableModels(timeoutMs) {
        const data = OmpModelsResultSchema.parse(
          await this.request({ type: "get_available_models" }, timeoutMs),
        );
        return data.models ?? [];
      }
      async setModel(provider: string, modelId: string): Promise<OmpModel> {
        return OmpModelSchema.parse(await this.request({ type: "set_model", provider, modelId }));
      }
      async setThinkingLevel(level: OmpThinkingLevel): Promise<void> {
        await this.request({ type: "set_thinking_level", level });
      }
      private request(command, timeoutMs) {
        return this.process.request(OmpRpcCommandSchema.parse(command), timeoutMs);
      }
    ''',
    "agent.ts": '''
      function parseModelReference(modelId: string | null) {
        const [provider, ...rest] = modelId.split("/");
        const id = rest.join("/");
        if (provider && id) { return { provider, id }; }
      }
      async setModel(modelId: string | null) {
        const model = await this.runtimeSession.setModel(parsedReference.provider, parsedReference.id);
        this.config.model = `${model.provider}/${model.id}`;
      }
      function modelToId(model) {
        return model?.provider && model.id ? `${model.provider}/${model.id}` : null;
      }
      async setThinkingOption(thinkingOptionId: string | null) {
        const thinkingLevel = normalizeOmpThinkingOption(thinkingOptionId) ?? DEFAULT_OMP_THINKING_LEVEL;
        await this.runtimeSession.setThinkingLevel(thinkingLevel);
      }
    ''',
    "runtime.ts": '''
      function appendOmpLaunchArgs(argv, session) {
        if (session.extraArgs?.length) argv.push(...session.extraArgs);
        if (session.model) argv.push("--model", session.model);
        if (session.thinkingOptionId) argv.push("--thinking", session.thinkingOptionId);
      }
    ''',
    "protocol-session.ts": '''
      export async function establishOmpProtocol(transport) {
        const response = await transport.request(
          { type: "negotiate_protocol", protocolVersion: 2 },
          requestTimeoutMs,
        );
      }
    ''',
}

# Synthetic release identity: fixtures never encode a production release pin.
VERSION = "9.8.7"
REVISION = "b" * 40
NIX_HASH = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
TAG_PAYLOAD = {"sha": REVISION}
RELEASE_PAYLOAD = {
    "tag_name": f"v{VERSION}",
    "assets": [{
        "name": f"Paseo-{VERSION}-arm64.dmg",
        "digest": "sha256:" + "0" * 64,
    }],
}


class PaseoTransportEvidenceTests(unittest.TestCase):
    def make_root(self, root):
        (root / "home/.paseo").mkdir(parents=True)
        (root / "packages").mkdir()
        (root / "modules").mkdir()
        (root / "release-pins.json").write_text(json.dumps({
            "paseo": {
                "version": VERSION,
                "hash": NIX_HASH,
            },
        }))
        (root / "packages/paseo.nix").write_text(r'''release = (builtins.fromJSON (builtins.readFile ../release-pins.json)).paseo;
url = "https://github.com/getpaseo/paseo/releases/download/v${release.version}/Paseo-${release.version}-arm64.dmg";
inherit (release) hash;
exec "$out/Applications/Paseo.app/Contents/Resources/bin/paseo" "\$@"
''')
        (root / "modules/darwin.nix").write_text('environment.systemPackages = [ (pkgs.callPackage ../packages/paseo.nix { }) ];\n')
        (root / "modules/home-manager.nix").write_text('''paseoConfig = builtins.fromJSON (builtins.readFile ../home/.paseo/config.json);
".paseo/config.json".text = builtins.toJSON (
''')
        (root / "home/.paseo/config.json").write_text(json.dumps({
            "daemon": {"agentProfiles": [{"provider": "omp", "model": "openai-codex/gpt-6-sol"}]},
            "agents": {"providers": {"omp": {"enabled": True, "additionalModels": []}}},
        }))

    def fake_fetch(self, source_texts=None):
        source_texts = dict(SOURCE_TEXTS if source_texts is None else source_texts)
        raw_base = f"https://raw.githubusercontent.com/getpaseo/paseo/{REVISION}"

        def fetch(url):
            if url == f"{paseo_support.API_BASE}/commits/v{VERSION}":
                return json.dumps(TAG_PAYLOAD)
            if url == f"{paseo_support.API_BASE}/releases/tags/v{VERSION}":
                return json.dumps(RELEASE_PAYLOAD)
            for path, text in source_texts.items():
                if url == f"{raw_base}/packages/server/src/server/agent/providers/omp/{path}":
                    return text
            raise AssertionError(f"unexpected source URL: {url}")

        return fetch

    def make_source(self, root, source_texts=None):
        source = paseo_support.collect(root, self.fake_fetch(source_texts))
        source["omp_revision"] = "a" * 40
        source["models"] = ["gpt-6-sol", "gpt-6.1-terra"]
        return source

    def test_collects_source_only_transport_proof_and_accepts_omp_intersection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            source = paseo_support.collect(root, self.fake_fetch())
            self.assertEqual(source["models"], [])
            self.assertEqual(source["kind"], "static-transport")
            self.assertEqual(source["pin_revision"], f"v{VERSION}")
            self.assertEqual(source["revision"], REVISION)
            self.assertEqual(len(source["transport_proofs"]), 6)
            self.assertEqual(source["provenance"]["nix_hash"], NIX_HASH)

            source["omp_revision"] = "a" * 40
            source["models"] = ["gpt-6-sol", "gpt-6.1-terra"]
            paseo_support.validate_source(root, source)

    def test_rejects_provider_rewrite_in_model_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            changed = dict(SOURCE_TEXTS)
            changed["map-omp-model.ts"] = changed["map-omp-model.ts"].replace(
                'id: `${model.provider}/${model.id}`,',
                'id: `wrong-provider/${model.id}`,'
            )
            with self.assertRaisesRegex(ValueError, "provider/model identity"):
                paseo_support.collect(root, self.fake_fetch(changed))

    def test_rejects_model_id_passthrough_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            changed = dict(SOURCE_TEXTS)
            changed["cli-runtime.ts"] = changed["cli-runtime.ts"].replace(
                '{ type: "set_model", provider, modelId }',
                '{ type: "set_model", provider, modelId: normalizeModel(modelId) }'
            )
            with self.assertRaisesRegex(ValueError, "provider and modelId are sent unchanged"):
                paseo_support.collect(root, self.fake_fetch(changed))

    def test_rejects_revision_mismatch_and_missing_transport_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            source = self.make_source(root)
            wrong_revision = dict(source, revision="0" * 40)
            with self.assertRaisesRegex(ValueError, "source URL or source tier is not pinned"):
                paseo_support.validate_source(root, wrong_revision)

            missing_proof = dict(source, transport_proofs=source["transport_proofs"][:-1])
            with self.assertRaisesRegex(ValueError, "missing pinned source proofs"):
                paseo_support.validate_source(root, missing_proof)

    def test_rejects_release_digest_and_tag_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            fetch = self.fake_fetch()
            for payload in (
                dict(RELEASE_PAYLOAD, tag_name="v0.0.0"),
                dict(RELEASE_PAYLOAD, assets=[{
                    "name": f"Paseo-{VERSION}-arm64.dmg",
                    "digest": "sha256:" + "f" * 64,
                }]),
            ):
                with self.subTest(payload=payload):
                    def changed_fetch(url):
                        if url.endswith(f"/releases/tags/v{VERSION}"):
                            return json.dumps(payload)
                        return fetch(url)
                    with self.assertRaisesRegex(ValueError, "release metadata|release digest"):
                        paseo_support.collect(root, changed_fetch)

    def test_comments_cannot_supply_missing_transport_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            changed = dict(SOURCE_TEXTS)
            changed["cli-runtime.ts"] = changed["cli-runtime.ts"].replace(
                'await this.request({ type: "set_thinking_level", level });',
                '// await this.request({ type: "set_thinking_level", level });',
            )
            with self.assertRaisesRegex(ValueError, "effort is forwarded unchanged"):
                paseo_support.collect(root, self.fake_fetch(changed))

    def test_rejects_non_omp_paseo_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_root(root)
            source = self.make_source(root)
            config_path = root / "home/.paseo/config.json"
            config = json.loads(config_path.read_text())
            config["agents"]["providers"]["omp"]["enabled"] = False
            config_path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "does not enable the external omp provider"):
                paseo_support.validate_source(root, source)


if __name__ == "__main__":
    unittest.main()
