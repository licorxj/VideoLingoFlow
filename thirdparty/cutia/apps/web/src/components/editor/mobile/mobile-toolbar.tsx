"use client";

import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import {
	AiBrain01Icon,
	Folder03Icon,
	Happy01Icon,
	HeadphonesIcon,
	TextIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react";
import { cn } from "@/utils/ui";
import { useMobileDrawerStore } from "./hooks/use-mobile-drawer";

type TabKey = "assets" | "text" | "sticker" | "audio" | "ai";

interface TabConfig {
	key: TabKey;
	icon: IconSvgElement;
	labelKey: string;
}

const TABS: TabConfig[] = [
	{ key: "assets", icon: Folder03Icon, labelKey: "Assets" },
	{ key: "text", icon: TextIcon, labelKey: "Text" },
	{ key: "sticker", icon: Happy01Icon, labelKey: "Stickers" },
	{ key: "audio", icon: HeadphonesIcon, labelKey: "Audio" },
	{ key: "ai", icon: AiBrain01Icon, labelKey: "AI" },
];

export function MobileToolbar() {
	const { t } = useTranslation();
	const activeDrawer = useMobileDrawerStore((s) => s.activeDrawer);
	const toggleDrawer = useMobileDrawerStore((s) => s.toggleDrawer);

	return (
		<nav className="bg-background flex items-center justify-around border-t px-1 pb-[calc(0.375rem+env(safe-area-inset-bottom))] pt-1.5">
			{TABS.map((tab) => {
				const isActive = activeDrawer === tab.key;

				const handlePress = () => {
					toggleDrawer({ drawer: tab.key });
				};

				return (
					<button
						key={tab.key}
						type="button"
						className={cn(
							"flex flex-col items-center gap-0.5 rounded-md px-3 py-1 text-xs transition-colors",
							isActive ? "text-primary" : "text-muted-foreground",
						)}
						onClick={handlePress}
						onKeyDown={(event) => {
							if (event.key === "Enter" || event.key === " ") {
								event.preventDefault();
								handlePress();
							}
						}}
						aria-label={t(tab.labelKey)}
						aria-pressed={isActive}
					>
						<HugeiconsIcon icon={tab.icon} className="size-5" />
						<span>{t(tab.labelKey)}</span>
					</button>
				);
			})}
		</nav>
	);
}
