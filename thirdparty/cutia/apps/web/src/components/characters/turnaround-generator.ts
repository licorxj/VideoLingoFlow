import { resolveImageProvider } from "@/lib/ai/providers";
import { useAISettingsStore } from "@/stores/ai-settings-store";

const CHARACTER_PORTRAIT_PROMPT_PREFIX =
	"character portrait, front facing view, full body from head to feet, nothing cropped, arms relaxed at sides, hands naturally hanging down, white background, clean design, high quality";

export function buildCharacterPortraitPrompt({
	description,
}: {
	description: string;
}): string {
	return `${CHARACTER_PORTRAIT_PROMPT_PREFIX}, ${description}`;
}

export async function generateCharacterPortrait({
	description,
}: {
	description: string;
}): Promise<{ url: string }> {
	const { imageProviderId, imageApiKey } = useAISettingsStore.getState();

	// 嵌入主项目时回落到 VideoLingo 接口层（无需 Cutia 侧 Key）
	const resolved = resolveImageProvider({
		id: imageProviderId,
		apiKey: imageApiKey,
	});
	if (!resolved) {
		throw new Error(
			"No image AI provider configured. Please set up an image provider and API key in Settings.",
		);
	}
	const { provider, apiKey } = resolved;

	const prompt = buildCharacterPortraitPrompt({ description });

	const results = await provider.generateImage({
		request: { prompt, aspectRatio: "9:16" },
		apiKey,
	});

	if (results.length === 0) {
		throw new Error("No images were generated");
	}

	return { url: results[0].url };
}
