"use client";

import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
	useCharacterStore,
	storeCharacterImageBlob,
	createImageThumbnailDataUrl,
	getCharacterImageBlob,
} from "@/stores/character-store";
import { generateCharacterPortrait } from "./turnaround-generator";
import { generateUUID } from "@/utils/id";
import { useAISettingsStore } from "@/stores/ai-settings-store";
import { HugeiconsIcon } from "@hugeicons/react";
import {
	Cancel01Icon,
	ImageAdd01Icon,
	Loading03Icon,
	SparklesIcon,
	Upload04Icon,
} from "@hugeicons/core-free-icons";
import type { AICharacter, CharacterImage } from "@/types/character";
import {
	analyzeImageWithVision,
	blobToDataUrl,
	DESCRIPTION_ANALYSIS_PROMPT,
	STYLE_ANALYSIS_PROMPT,
} from "@/lib/ai/vision";
import { useAgentStore } from "@/stores/agent-store";
import {
	ImageLightbox,
	useImageLightbox,
	type ImageSource,
} from "./image-lightbox";

interface CharacterCreatorProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	editCharacter?: AICharacter | null;
}

export function CharacterCreatorDialog({
	isOpen,
	onOpenChange,
	editCharacter,
}: CharacterCreatorProps) {
	const { t } = useTranslation();
	const { addCharacter, updateCharacter, addImage, removeImage } =
		useCharacterStore();
	const { imageProviderId, imageApiKey } = useAISettingsStore();

	const isEditing = editCharacter !== null && editCharacter !== undefined;

	const [name, setName] = useState(editCharacter?.name ?? "");
	const [description, setDescription] = useState(
		editCharacter?.description ?? "",
	);
	const [styleDescription, setStyleDescription] = useState(
		editCharacter?.styleDescription ?? "",
	);
	const [isGenerating, setIsGenerating] = useState(false);
	const [isAnalyzing, setIsAnalyzing] = useState(false);
	const agentConfig = useAgentStore((s) => s.config);
	const isAgentConfigured = agentConfig.apiKey.length > 0;
	const lightbox = useImageLightbox();
	const [previewImages, setPreviewImages] = useState<
		Array<{
			id: string;
			thumbnailDataUrl: string;
			label: string;
			blobKey: string;
			isNew: boolean;
		}>
	>(
		editCharacter?.images.map((img) => ({
			id: img.id,
			thumbnailDataUrl: img.thumbnailDataUrl,
			label: img.label,
			blobKey: img.blobKey,
			isNew: false,
		})) ?? [],
	);
	const [pendingImages, setPendingImages] = useState<
		Map<string, CharacterImage>
	>(new Map());

	const isProviderConfigured =
		imageProviderId !== null && imageApiKey.length > 0;

	const handleGenerateTurnaround = useCallback(async () => {
		if (!description.trim()) {
			toast.error(t("Please enter a character description first"));
			return;
		}
		setIsGenerating(true);
		try {
			const result = await generateCharacterPortrait({
				description: description.trim(),
			});

			const response = await fetch(result.url);
			const blob = await response.blob();

			const blobKey = generateUUID();
			await storeCharacterImageBlob({ id: blobKey, blob });
			const thumbnailDataUrl = await createImageThumbnailDataUrl({
				blob,
			});

			const imageId = generateUUID();
			const characterImage: CharacterImage = {
				id: imageId,
				label: "Character Portrait",
				prompt: description.trim(),
				blobKey,
				thumbnailDataUrl,
				createdAt: new Date().toISOString(),
			};

			setPendingImages((prev) => new Map(prev).set(imageId, characterImage));
			setPreviewImages((prev) => [
				...prev,
				{
					id: imageId,
					thumbnailDataUrl,
					label: "Character Portrait",
					blobKey,
					isNew: true,
				},
			]);

			toast.success(t("Character portrait generated"));
		} catch (error) {
			toast.error(
				error instanceof Error
					? error.message
					: t("Failed to generate character portrait"),
			);
		} finally {
			setIsGenerating(false);
		}
	}, [description, t]);

	const handleUploadImage = useCallback(() => {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = "image/png,image/jpeg,image/webp,image/gif";
		input.addEventListener("change", async () => {
			const file = input.files?.[0];
			if (!file) return;

			try {
				const blob = new Blob([await file.arrayBuffer()], {
					type: file.type,
				});
				const blobKey = generateUUID();
				await storeCharacterImageBlob({ id: blobKey, blob });
				const thumbnailDataUrl = await createImageThumbnailDataUrl({
					blob,
				});

				const imageId = generateUUID();
				const characterImage: CharacterImage = {
					id: imageId,
					label: file.name.replace(/\.\w+$/, ""),
					prompt: "",
					blobKey,
					thumbnailDataUrl,
					createdAt: new Date().toISOString(),
				};

				setPendingImages((prev) =>
					new Map(prev).set(imageId, characterImage),
				);
				setPreviewImages((prev) => [
					...prev,
					{
						id: imageId,
						thumbnailDataUrl,
						label: characterImage.label,
						blobKey,
						isNew: true,
					},
				]);
			} catch {
				toast.error(t("Failed to upload image"));
			}
		});
		input.click();
	}, [t]);

	const handleRemovePreview = useCallback(
		({ imageId }: { imageId: string }) => {
			setPreviewImages((prev) => prev.filter((p) => p.id !== imageId));
			setPendingImages((prev) => {
				const next = new Map(prev);
				next.delete(imageId);
				return next;
			});
			if (isEditing && editCharacter) {
				const existingImage = editCharacter.images.find(
					(i) => i.id === imageId,
				);
				if (existingImage) {
					removeImage({ characterId: editCharacter.id, imageId });
				}
			}
		},
		[isEditing, editCharacter, removeImage],
	);

	const resetForm = useCallback(() => {
		setName("");
		setDescription("");
		setStyleDescription("");
		setPreviewImages([]);
		setPendingImages(new Map());
	}, []);

	const handleSave = useCallback(() => {
		const trimmedName = name.trim();
		if (!trimmedName) {
			toast.error(t("Please enter a character name"));
			return;
		}

		const trimmedStyleDesc = styleDescription.trim() || undefined;

		if (isEditing && editCharacter) {
			updateCharacter({
				id: editCharacter.id,
				updates: {
					name: trimmedName,
					description: description.trim(),
					styleDescription: trimmedStyleDesc,
				},
			});
			for (const image of pendingImages.values()) {
				addImage({ characterId: editCharacter.id, image });
			}
		} else {
			const characterId = addCharacter({
				name: trimmedName,
				description: description.trim(),
			});
			if (trimmedStyleDesc) {
				updateCharacter({
					id: characterId,
					updates: { styleDescription: trimmedStyleDesc },
				});
			}
			for (const image of pendingImages.values()) {
				addImage({ characterId, image });
			}
		}

		onOpenChange(false);
		resetForm();
	}, [
		name,
		description,
		styleDescription,
		isEditing,
		editCharacter,
		pendingImages,
		addCharacter,
		updateCharacter,
		addImage,
		onOpenChange,
		resetForm,
		t,
	]);

	const handleAnalyzeFromImage = useCallback(async () => {
		const firstImage = previewImages[0];
		if (!firstImage) {
			toast.error(t("Please upload a reference image first"));
			return;
		}

		setIsAnalyzing(true);
		try {
			const blob = await getCharacterImageBlob({
				id: firstImage.blobKey,
			});
			if (!blob) {
				toast.error(t("Failed to load reference image"));
				return;
			}

			const imageDataUrl = await blobToDataUrl({ blob });

			const [descResult, styleResult] = await Promise.all([
				analyzeImageWithVision({
					imageDataUrl,
					analysisPrompt: DESCRIPTION_ANALYSIS_PROMPT,
				}),
				analyzeImageWithVision({
					imageDataUrl,
					analysisPrompt: STYLE_ANALYSIS_PROMPT,
				}),
			]);

			if (descResult) setDescription(descResult);
			if (styleResult) setStyleDescription(styleResult);

			toast.success(t("Description and style generated from image"));
		} catch (error) {
			toast.error(
				error instanceof Error
					? error.message
					: t("Failed to analyze image"),
			);
		} finally {
			setIsAnalyzing(false);
		}
	}, [previewImages, t]);

	const handleOpenChange = (open: boolean) => {
		if (!open) {
			resetForm();
		}
		onOpenChange(open);
	};

	return (
		<>
		<Dialog open={isOpen} onOpenChange={handleOpenChange}>
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>
						{isEditing
							? t("Edit Character")
							: t("Create Character")}
					</DialogTitle>
				</DialogHeader>

				<DialogBody>
					<div className="flex flex-col gap-2">
						<Label htmlFor="character-name">{t("Name")}</Label>
						<Input
							id="character-name"
							placeholder={t("Character name")}
							value={name}
							onChange={(event) => setName(event.target.value)}
						/>
					</div>

					<div className="flex flex-col gap-2">
						<div className="flex items-center justify-between">
							<Label htmlFor="character-description">
								{t("Description")}
							</Label>
							{previewImages.length > 0 &&
								isAgentConfigured && (
									<Button
										type="button"
										variant="ghost"
										size="sm"
										className="h-6 gap-1 px-2 text-xs"
										disabled={isAnalyzing}
										onClick={handleAnalyzeFromImage}
										onKeyDown={(event) => {
											if (event.key === "Enter")
												handleAnalyzeFromImage();
										}}
									>
										{isAnalyzing ? (
											<HugeiconsIcon
												icon={Loading03Icon}
												className="size-3 animate-spin"
											/>
										) : (
											<HugeiconsIcon
												icon={SparklesIcon}
												className="size-3"
											/>
										)}
										{t("Generate from image")}
									</Button>
								)}
						</div>
						<Textarea
							id="character-description"
							placeholder={t(
								"Describe the character's appearance: gender, hair, clothing, accessories, body type, etc.",
							)}
							value={description}
							onChange={(event) =>
								setDescription(event.target.value)
							}
							rows={4}
						/>
						<p className="text-muted-foreground text-xs">
							{t(
								"Auto-injected into AI generation prompts for consistent character appearance.",
							)}
						</p>
					</div>

					<div className="flex flex-col gap-2">
						<Label htmlFor="character-style-description">
							{t("Style Lock")}{" "}
							<span className="text-muted-foreground font-normal">
								({t("optional")})
							</span>
						</Label>
						<Textarea
							id="character-style-description"
							placeholder={t(
								"Art style, color palette, lighting, rendering approach... e.g. 'Pixar 3D style, warm lighting, vibrant colors'",
							)}
							value={styleDescription}
							onChange={(event) =>
								setStyleDescription(event.target.value)
							}
							rows={2}
						/>
						<p className="text-muted-foreground text-xs">
							{t(
								"Ensures all generated content maintains a consistent visual style.",
							)}
						</p>
					</div>

					<div className="flex flex-col gap-2">
						<Label>{t("Reference Images")}</Label>
						<div className="flex flex-wrap gap-2">
							{previewImages.map((preview, index) => {
								const allSources: ImageSource[] =
									previewImages.map((p) => ({
										type: "blob" as const,
										blobKey: p.blobKey,
										label: p.label,
									}));
								return (
								<div
									key={preview.id}
									className="group/img relative size-20 overflow-hidden rounded-md border"
								>
									<button
										type="button"
										className="size-full cursor-pointer"
										onClick={() =>
											lightbox.open({
												sources: allSources,
												index,
											})
										}
										onKeyDown={(event) => {
											if (event.key === "Enter")
												lightbox.open({
													sources: allSources,
													index,
												});
										}}
										title={t("Click to view full image")}
									>
										{/* biome-ignore lint: data URL thumbnail */}
										<img
											src={preview.thumbnailDataUrl}
											alt={preview.label}
											className="size-full object-cover"
										/>
									</button>
									<button
										type="button"
										className="absolute top-0.5 right-0.5 rounded-full bg-black/60 p-0.5 opacity-0 transition-opacity hover:bg-black/80 group-hover/img:opacity-100"
										onClick={() =>
											handleRemovePreview({
												imageId: preview.id,
											})
										}
										onKeyDown={(event) => {
											if (event.key === "Enter")
												handleRemovePreview({
													imageId: preview.id,
												});
										}}
									>
										<HugeiconsIcon
											icon={Cancel01Icon}
											className="size-3 text-white"
										/>
									</button>
								</div>
								);
							})}
						</div>

						<div className="flex gap-2">
							<Button
								type="button"
								variant="outline"
								size="sm"
								disabled={
									isGenerating ||
									!isProviderConfigured ||
									!description.trim()
								}
								onClick={handleGenerateTurnaround}
								onKeyDown={(event) => {
									if (event.key === "Enter")
										handleGenerateTurnaround();
								}}
								className="flex-1"
							>
								{isGenerating ? (
									<>
										<HugeiconsIcon
											icon={Loading03Icon}
											className="mr-1 size-4 animate-spin"
										/>
										{t("Generating...")}
									</>
								) : (
									<>
										<HugeiconsIcon
											icon={ImageAdd01Icon}
											className="mr-1 size-4"
										/>
										{t("Generate Portrait")}
									</>
								)}
							</Button>
							<Button
								type="button"
								variant="outline"
								size="sm"
								onClick={handleUploadImage}
								onKeyDown={(event) => {
									if (event.key === "Enter")
										handleUploadImage();
								}}
							>
								<HugeiconsIcon
									icon={Upload04Icon}
									className="mr-1 size-4"
								/>
								{t("Upload")}
							</Button>
						</div>

						{!isProviderConfigured && (
							<p className="text-muted-foreground text-xs">
								{t(
									"Configure an image provider in editor Settings to generate character portraits.",
								)}
							</p>
						)}
					</div>
				</DialogBody>

				<DialogFooter>
					<Button
						type="button"
						variant="outline"
						onClick={() => handleOpenChange(false)}
						onKeyDown={(event) => {
							if (event.key === "Enter") handleOpenChange(false);
						}}
					>
						{t("Cancel")}
					</Button>
					<Button
						type="button"
						onClick={handleSave}
						onKeyDown={(event) => {
							if (event.key === "Enter") handleSave();
						}}
						disabled={!name.trim()}
					>
						{isEditing ? t("Save") : t("Create")}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
		<ImageLightbox
			state={lightbox.state}
			onClose={lightbox.close}
			onPrev={lightbox.prev}
			onNext={lightbox.next}
		/>
		</>
	);
}
