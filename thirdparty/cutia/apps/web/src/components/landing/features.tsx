"use client";

import { Shield, Globe, Code2, Sparkles, Layers, MonitorPlay } from "lucide-react";
import { motion } from "motion/react";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function Features() {
	const { t } = useTranslation();
	const features = [
		{
			icon: Sparkles,
			title: t("AI-Native"),
			description: t(
				"AI is built into every step of your workflow. Generate images, transcribe audio, create captions, and let the AI agent edit videos for you.",
			),
		},
		{
			icon: Shield,
			title: t("Privacy First"),
			description: t(
				"Your files never leave your device. All processing happens locally in your browser — no uploads, no servers.",
			),
		},
		{
			icon: Globe,
			title: t("Works Everywhere"),
			description: t(
				"No installation needed. Open your browser on any platform and start editing right away.",
			),
		},
		{
			icon: Code2,
			title: t("Open Source"),
			description: t(
				"Fully open source and community-driven. Inspect the code, contribute, or fork it for your needs.",
			),
		},
		{
			icon: Layers,
			title: t("Multi-track Timeline"),
			description: t(
				"Professional timeline with support for video, audio, text, and sticker tracks. Drag, trim, and split with ease.",
			),
		},
		{
			icon: MonitorPlay,
			title: t("Export Anywhere"),
			description: t(
				"Export your projects in MP4 or WebM format with adjustable quality settings.",
			),
		},
	] as const;

	return (
		<section id="features" className="relative px-4 py-24 md:py-32">
			<div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-primary/[0.03] via-transparent to-transparent dark:from-transparent" />
			<div className="mx-auto max-w-6xl">
				<motion.div
					className="mb-16 text-center"
					initial={{ opacity: 0, y: 30 }}
					whileInView={{ opacity: 1, y: 0 }}
					viewport={{ once: true, margin: "-100px" }}
					transition={{ duration: 0.6, ease: "easeOut" }}
				>
					<h2 className="mb-4 text-3xl font-bold tracking-tight md:text-4xl">
						{t("Everything you need to edit")}
					</h2>
					<p className="text-muted-foreground mx-auto max-w-2xl text-lg">
						{t(
							"A focused set of tools designed for clarity and speed. No feature bloat — just what matters.",
						)}
					</p>
				</motion.div>

				<div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
					{features.map((feature, index) => (
						<motion.div
							key={feature.title}
							className="group rounded-2xl border border-border/50 bg-card/50 p-6 shadow-sm backdrop-blur-sm transition-all hover:border-border hover:bg-card hover:shadow-md dark:shadow-none dark:hover:shadow-none"
							initial={{ opacity: 0, y: 40 }}
							whileInView={{ opacity: 1, y: 0 }}
							viewport={{ once: true, margin: "-60px" }}
							transition={{
								duration: 0.5,
								delay: index * 0.1,
								ease: "easeOut",
							}}
							whileHover={{ y: -4, transition: { duration: 0.2 } }}
						>
							<motion.div
								className="mb-4 flex size-11 items-center justify-center rounded-xl bg-primary/8 dark:bg-foreground/10"
								whileHover={{ scale: 1.1, rotate: 5 }}
								transition={{ type: "spring", stiffness: 400, damping: 15 }}
							>
								<feature.icon className="size-5 text-primary/70 dark:text-foreground/70" />
							</motion.div>
							<h3 className="mb-2 text-lg font-semibold">{feature.title}</h3>
							<p className="text-muted-foreground text-sm leading-relaxed">
								{feature.description}
							</p>
						</motion.div>
					))}
				</div>
			</div>
		</section>
	);
}
