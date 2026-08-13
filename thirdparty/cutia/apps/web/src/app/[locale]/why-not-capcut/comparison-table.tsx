"use client";

import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Check, X, Minus } from "lucide-react";

type FeatureStatus = "yes" | "no" | "partial";

interface ComparisonRow {
	feature: string;
	cutia: FeatureStatus;
	cutiaNote: string;
	capcut: FeatureStatus;
	capcutNote: string;
	capcutSourceUrl?: string;
	capcutSourceLabel?: string;
}

function StatusIcon({ status }: { status: FeatureStatus }) {
	if (status === "yes") {
		return <Check className="inline size-4 text-green-500" />;
	}
	if (status === "no") {
		return <X className="inline size-4 text-red-500" />;
	}
	return <Minus className="inline size-4 text-yellow-500" />;
}

export function ComparisonTable() {
	const { t } = useTranslation();

	const rows: ComparisonRow[] = [
		{
			feature: t("Price"),
			cutia: "yes",
			cutiaNote: t("100% free, no premium tiers"),
			capcut: "partial",
			capcutNote: t("Free tier with paid Pro plan"),
		},
		{
			feature: t("Open Source"),
			cutia: "yes",
			cutiaNote: t("Fully open source on GitHub"),
			capcut: "no",
			capcutNote: t("Closed-source proprietary"),
		},
		{
			feature: t("Privacy"),
			cutia: "yes",
			cutiaNote: t("Files stay on your device"),
			capcut: "no",
			capcutNote: t("Files uploaded to servers"),
			capcutSourceUrl:
				"https://www.capcut.net/clause/privacy",
			capcutSourceLabel: t("Source: CapCut Privacy Policy, Section I"),
		},
		{
			feature: t("Account Required"),
			cutia: "yes",
			cutiaNote: t("No sign-up needed"),
			capcut: "no",
			capcutNote: t("Account required"),
		},
		{
			feature: t("Watermark-Free Export"),
			cutia: "yes",
			cutiaNote: t("Never adds watermarks"),
			capcut: "partial",
			capcutNote: t("Watermark on free tier exports"),
		},
		{
			feature: t("Browser-Based"),
			cutia: "yes",
			cutiaNote: t("Runs entirely in your browser"),
			capcut: "partial",
			capcutNote: t("Web version available, desktop app preferred"),
		},
		{
			feature: t("AI Features"),
			cutia: "yes",
			cutiaNote: t("AI agent, image generation, transcription"),
			capcut: "yes",
			capcutNote: t("AI-powered editing features"),
		},
		{
			feature: t("Multi-Track Timeline"),
			cutia: "yes",
			cutiaNote: t("Video, audio, text, sticker tracks"),
			capcut: "yes",
			capcutNote: t("Full multi-track timeline"),
		},
		{
			feature: t("Export Formats"),
			cutia: "partial",
			cutiaNote: t("MP4 and WebM"),
			capcut: "yes",
			capcutNote: t("MP4, MOV, and more"),
		},
		{
			feature: t("Offline Editing"),
			cutia: "yes",
			cutiaNote: t("Works offline after initial load"),
			capcut: "partial",
			capcutNote: t("Desktop app works offline"),
		},
		{
			feature: t("No Installation"),
			cutia: "yes",
			cutiaNote: t("Just open the website"),
			capcut: "no",
			capcutNote: t("Desktop app requires installation"),
		},
		{
			feature: t("Self-Hostable"),
			cutia: "yes",
			cutiaNote: t("Deploy on your own server"),
			capcut: "no",
			capcutNote: t("Not available for self-hosting"),
		},
	];

	return (
		<section className="flex flex-col gap-4">
			<h2 className="text-2xl font-semibold">
				{t("Feature-by-feature comparison")}
			</h2>
			<div className="rounded-lg border">
				<Table>
					<TableHeader>
						<TableRow>
							<TableHead className="w-[200px] font-semibold">
								{t("Feature")}
							</TableHead>
							<TableHead className="font-semibold text-green-600 dark:text-green-400">
								Cutia
							</TableHead>
							<TableHead className="font-semibold">CapCut</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{rows.map((row) => (
							<TableRow key={row.feature}>
								<TableCell className="font-medium">
									{row.feature}
								</TableCell>
								<TableCell>
									<div className="flex items-center gap-2">
										<StatusIcon status={row.cutia} />
										<span className="text-muted-foreground text-sm">
											{row.cutiaNote}
										</span>
									</div>
								</TableCell>
							<TableCell>
								<div className="flex items-center gap-2">
									<StatusIcon status={row.capcut} />
									<div className="flex flex-col gap-0.5">
										<span className="text-muted-foreground text-sm">
											{row.capcutNote}
										</span>
										{row.capcutSourceUrl && (
											<a
												href={row.capcutSourceUrl}
												target="_blank"
												rel="noopener noreferrer"
												className="text-xs text-blue-500 hover:underline"
											>
												{row.capcutSourceLabel}
											</a>
										)}
									</div>
								</div>
							</TableCell>
							</TableRow>
						))}
					</TableBody>
				</Table>
			</div>
		</section>
	);
}
