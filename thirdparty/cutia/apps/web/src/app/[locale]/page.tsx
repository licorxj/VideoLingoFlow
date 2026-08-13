import { Hero } from "@/components/landing/hero";
import { Features } from "@/components/landing/features";
import { FAQSection } from "@/components/landing/faq-section";
import { CTASection } from "@/components/landing/cta-section";
import { StarField } from "@/components/landing/starfield";
import { HomepageJsonLd } from "@/components/landing/homepage-json-ld";
import { Header } from "@/components/header";
import { Footer } from "@/components/footer";
import type { Metadata } from "next";
import { SITE_URL } from "@/constants/site-constants";

export const metadata: Metadata = {
	alternates: {
		canonical: SITE_URL,
	},
	keywords: [
		"AI video editor",
		"AI-native video editor",
		"AI video editing",
		"CapCut alternative",
		"free CapCut alternative",
		"open source CapCut alternative",
		"browser video editor",
		"online video editor",
		"free video editor",
		"open source video editor",
		"privacy-first video editor",
		"no upload video editor",
		"video editor",
		"WebM editor",
		"MP4 editor",
	],
};

export default async function Home({
	params,
}: {
	params: Promise<{ locale: string }>;
}) {
	const { locale } = await params;

	return (
		<main className="min-h-svh">
			<HomepageJsonLd locale={locale} />
			<StarField />
			<Header />
			<Hero />
			<Features />
			<FAQSection />
			<CTASection />
			<Footer />
		</main>
	);
}
