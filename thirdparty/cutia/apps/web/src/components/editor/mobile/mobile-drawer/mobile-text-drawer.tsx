"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { TextView } from "../../panels/assets/views/text";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";

export function MobileTextDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "text";

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
					<DrawerTitle>{t("Text")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<TextView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
