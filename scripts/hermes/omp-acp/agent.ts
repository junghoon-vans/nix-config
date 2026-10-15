import * as fs from "node:fs/promises";
import * as path from "node:path";
import {
	createAcpSessionFactory,
	createAgentSession,
	discoverAuthStorage,
	ModelRegistry,
	Settings,
} from "@oh-my-pi/pi-coding-agent";
import { all } from "@oh-my-pi/pi-coding-agent/config/registry";
import { initializeWithSettings } from "@oh-my-pi/pi-coding-agent/discovery";
import { runAcpMode } from "@oh-my-pi/pi-coding-agent/modes/acp";
import { createAuthStorageSettingsSync } from "@oh-my-pi/pi-coding-agent/session/auth-broker-config";
import { cfgToolsApproval, cfgToolsApprovalMode } from "@oh-my-pi/pi-coding-agent/tools/settings";

const TOOL_NAMES = ["read", "grep", "glob", "edit", "write", "bash", "lsp", "todo"];
const REQUIRED_TOOL_APPROVALS = {
	bash: "prompt",
	edit: "prompt",
	write: "prompt",
	lsp: "prompt",
} as const;

class UsageError extends Error {}

function parsePolicyPath(args: string[]): string {
	if (args.length !== 2 || args[0] !== "--policy") {
		throw new UsageError("Usage: hermes-omp-acp --policy /absolute/path/to/policy.yaml");
	}

	const policyPath = args[1];
	if (!path.isAbsolute(policyPath)) {
		throw new UsageError("--policy must be an absolute YAML path");
	}
	return policyPath;
}

async function requirePolicyFile(policyPath: string): Promise<void> {
	let isFile = false;
	try {
		isFile = (await fs.stat(policyPath)).isFile();
	} catch {}
	if (!isFile) throw new UsageError("--policy must name an existing YAML file");
}

function assertPolicyOverlay(settings: Settings): void {
	if (
		settings.getProvenance(cfgToolsApprovalMode) !== "overlay" ||
		cfgToolsApprovalMode.get(settings) !== "always-ask"
	) {
		throw new Error("The --policy YAML must set tools.approvalMode to always-ask");
	}

	const approval = cfgToolsApproval.get(settings);
	if (
		settings.getProvenance(cfgToolsApproval) !== "overlay" ||
		Object.entries(REQUIRED_TOOL_APPROVALS).some(([tool, mode]) => approval[tool] !== mode)
	) {
		throw new Error("The --policy YAML must set tools.approval for bash, edit, write, and lsp to prompt");
	}
}

function applyProtocolDefaults(settings: Settings): void {
	for (const setting of all()) {
		if (setting.definition.protocolDefault?.includes("acp")) setting.pinDefault(settings);
	}
}

function enforceToolApproval(settings: Settings): void {
	cfgToolsApprovalMode.override(settings, "always-ask");
	cfgToolsApproval.override(settings, {
		...cfgToolsApproval.get(settings),
		...REQUIRED_TOOL_APPROVALS,
	});
}

async function main(): Promise<void> {
	const policyPath = parsePolicyPath(process.argv.slice(2));
	await requirePolicyFile(policyPath);

	// Match OMP's normal ACP startup: user settings/auth/model roles remain active,
	// while the Nix-owned policy file is the last config overlay for every workspace.
	process.env.PI_NO_TITLE = "1";
	const cwd = process.cwd();
	const settingsInstance = await Settings.init({ cwd, configFiles: [policyPath] });
	assertPolicyOverlay(settingsInstance);
	applyProtocolDefaults(settingsInstance);
	// Re-apply the non-negotiable approvals as runtime overrides so a per-project
	// settings file can never weaken the service's policy for a later ACP workspace.
	enforceToolApproval(settingsInstance);

	const authStorage = await discoverAuthStorage(undefined, { settings: settingsInstance });
	createAuthStorageSettingsSync(settingsInstance, authStorage);
	const modelRegistry = new ModelRegistry(authStorage, undefined, { settings: settingsInstance });
	await modelRegistry.hydrateCredentialScopedModelCaches();
	initializeWithSettings(settingsInstance);

	const createSession = createAcpSessionFactory({
		baseOptions: {
			cwd,
			settings: settingsInstance,
			authStorage,
			modelRegistry,
			toolNames: [...TOOL_NAMES],
			restrictToolNames: true,
			disableExtensionDiscovery: true,
			preloadedCustomToolPaths: [],
			enableMCP: false,
			enableLsp: true,
			lspReadOnly: true,
			hasUI: false,
			settingsApproval: false,
			tuiTranscript: false,
			autoTitle: false,
		},
		settings: settingsInstance,
		authStorage,
		modelRegistry,
		parsedArgs: { invalidFlagValues: [] },
		rawArgs: [],
		createSession: async options => {
			const result = await createAgentSession(options);
			modelRegistry.refreshInBackground();
			return result;
		},
	});

	await runAcpMode(createSession);
}

if (import.meta.main) {
	main().catch(error => {
		process.stderr.write(`hermes-omp-acp: ${error instanceof Error ? error.message : String(error)}\n`);
		process.exit(error instanceof UsageError ? 2 : 1);
	});
}
