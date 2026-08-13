"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { MediaView } from "../../panels/assets/views/media";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";

export function MobileAssetsDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "assets";

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
					<DrawerTitle>{t("Media")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<MediaView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
