"use client";

import { notFound } from "next/navigation";
import { IS_DEV } from "@/constants/editor-constants";
import { BasePage } from "@/app/base-page";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TranscriptionPlayground } from "./_components/transcription-playground";

if (!IS_DEV) {
	notFound();
}

export default function PlaygroundPage() {
	return (
		<BasePage title="Dev Playground" maxWidth="6xl">
			<Tabs defaultValue="transcription">
				<TabsList>
					<TabsTrigger value="transcription">Transcription</TabsTrigger>
				</TabsList>

				<TabsContent value="transcription" className="mt-6">
					<TranscriptionPlayground />
				</TabsContent>
			</Tabs>
		</BasePage>
	);
}
