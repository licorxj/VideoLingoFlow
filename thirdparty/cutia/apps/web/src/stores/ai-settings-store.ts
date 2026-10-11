import { IS_DEV } from "@/constants/editor-constants";
import { isHostEmbedded } from "@/lib/host/bridge";
import { VIDEOLINGO_PROVIDER_ID } from "@/lib/ai/providers/videolingo";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AISettingsState {
	imageProviderId: string | null;
	imageApiKey: string;
	videoProviderId: string | null;
	videoApiKey: string;
	devPlaceholderEnabled: boolean;

	setImageProvider: (providerId: string | null) => void;
	setImageApiKey: (apiKey: string) => void;
	setVideoProvider: (providerId: string | null) => void;
	setVideoApiKey: (apiKey: string) => void;
	setDevPlaceholderEnabled: (enabled: boolean) => void;
}

export const useAISettingsStore = create<AISettingsState>()(
	persist(
		(set) => ({
			// 嵌入主项目时默认走 VideoLingo 接口层，免去重复配置 Key
			imageProviderId: isHostEmbedded() ? VIDEOLINGO_PROVIDER_ID : null,
			imageApiKey: isHostEmbedded() ? "host" : "",
			videoProviderId: isHostEmbedded() ? VIDEOLINGO_PROVIDER_ID : null,
			videoApiKey: isHostEmbedded() ? "host" : "",
			devPlaceholderEnabled: IS_DEV,

			setImageProvider: (providerId) => set({ imageProviderId: providerId }),
			setImageApiKey: (apiKey) => set({ imageApiKey: apiKey }),
			setVideoProvider: (providerId) => set({ videoProviderId: providerId }),
			setVideoApiKey: (apiKey) => set({ videoApiKey: apiKey }),
			setDevPlaceholderEnabled: (enabled) =>
				set({ devPlaceholderEnabled: enabled }),
		}),
		{
			name: "ai-settings",
		},
	),
);
