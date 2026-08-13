import { SITE_URL } from "@/constants/site-constants";
import type { MetadataRoute } from "next";
import { i18nConfig } from "../i18n.config";

function buildAlternates({ path }: { path: string }) {
	const languages: Record<string, string> = {};
	for (const locale of i18nConfig.locales) {
		languages[locale] = `${SITE_URL}/${locale}${path}`;
	}
	languages["x-default"] = `${SITE_URL}/${i18nConfig.defaultLocale}${path}`;
	return { languages };
}

export default function sitemap(): MetadataRoute.Sitemap {
	const paths = [
		{ path: "", priority: 1, changeFrequency: "weekly" as const },
		{ path: "/roadmap", priority: 1, changeFrequency: "weekly" as const },
		{ path: "/privacy", priority: 0.5, changeFrequency: "monthly" as const },
		{ path: "/terms", priority: 0.5, changeFrequency: "monthly" as const },
		{
			path: "/why-not-capcut",
			priority: 1,
			changeFrequency: "yearly" as const,
		},
	];

	return paths.map(({ path, priority, changeFrequency }) => ({
		url: `${SITE_URL}/${i18nConfig.defaultLocale}${path}`,
		lastModified: new Date(),
		changeFrequency,
		priority,
		alternates: buildAlternates({ path }),
	}));
}
