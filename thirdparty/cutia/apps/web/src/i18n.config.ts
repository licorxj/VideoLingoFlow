import { createI18nConfig } from "@i18next-toolkit/nextjs-approuter";

export const i18nConfig = createI18nConfig({
	locales: [
		"en",
		"zh",
		"ja",
		"ko",
		"es",
		"pt",
		"fr",
		"de",
		"id",
		"vi",
		"ru",
		"it",
	],
	defaultLocale: "en",
	localeDir: "./public/locales",
	namespaces: ["translation"],
	routingStrategy: "url-segment",
});
