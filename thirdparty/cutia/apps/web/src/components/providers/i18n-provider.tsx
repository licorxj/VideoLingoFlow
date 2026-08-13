"use client";

import {
	I18nProvider as BaseI18nProvider,
	useTranslation,
} from "@i18next-toolkit/nextjs-approuter";
import type { I18nProviderProps } from "@i18next-toolkit/nextjs-approuter";
import { useEffect } from "react";
import { _setGlobalTranslation } from "@/lib/i18n";

function I18nInstanceBridge({ children }: { children: React.ReactNode }) {
	const { t } = useTranslation();

	useEffect(() => {
		_setGlobalTranslation({ t });
	}, [t]);

	return children;
}

export function I18nProvider({
	children,
	...props
}: I18nProviderProps) {
	return (
		<BaseI18nProvider {...props}>
			<I18nInstanceBridge>{children}</I18nInstanceBridge>
		</BaseI18nProvider>
	);
}
