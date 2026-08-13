"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { SoundsView } from "../../panels/assets/views/sounds";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";

export function MobileAudioDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "audio";

	return (
		<Drawer
			open={isOpen}
			onOpenChange={(open) => {
				if (!open) closeDrawer();
			}}
			shouldScaleBackground={false}
		>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Sounds")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<SoundsView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
