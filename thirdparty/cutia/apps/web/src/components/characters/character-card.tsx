"use client";

import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import type { AICharacter } from "@/types/character";
import { HugeiconsIcon } from "@hugeicons/react";
import {
	Delete02Icon,
	Edit03Icon,
	MoreHorizontalIcon,
	UserIcon,
} from "@hugeicons/core-free-icons";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { getCharacterImageBlob } from "@/stores/character-store";

export function CharacterCard({
	character,
	onClick,
	onEdit,
	onDelete,
}: {
	character: AICharacter;
	onClick: () => void;
	onEdit: () => void;
	onDelete: () => void;
}) {
	const { t } = useTranslation();
	const [isMenuOpen, setIsMenuOpen] = useState(false);
	const [hdUrl, setHdUrl] = useState<string | null>(null);

	const firstBlobKey = character.images[0]?.blobKey;

	useEffect(() => {
		if (!firstBlobKey) return;

		let revoked = false;
		void getCharacterImageBlob({ id: firstBlobKey }).then((blob) => {
			if (revoked || !blob) return;
			setHdUrl(URL.createObjectURL(blob));
		});

		return () => {
			revoked = true;
			setHdUrl((prev) => {
				if (prev) URL.revokeObjectURL(prev);
				return null;
			});
		};
	}, [firstBlobKey]);

	const totalGenerations = character.generations.length;
	const totalImages = character.images.length;
	const displaySrc = hdUrl ?? character.thumbnailDataUrl;

	return (
		<div className="group relative">
			<button
				type="button"
				className="block w-full text-left"
				onClick={onClick}
				onKeyDown={(event) => {
					if (event.key === "Enter") onClick();
				}}
			>
				<div className="bg-background overflow-hidden rounded-lg border p-0 transition-colors hover:border-foreground/20">
					<div className="bg-muted relative aspect-[4/3]">
						{displaySrc ? (
							/* biome-ignore lint: data URL or blob URL */
							<img
								src={displaySrc}
								alt={character.name}
								className="size-full object-cover"
							/>
						) : (
							<div className="flex size-full items-center justify-center">
								<HugeiconsIcon
									icon={UserIcon}
									className="text-muted-foreground size-12"
								/>
							</div>
						)}

						{totalImages > 0 && (
							<div className="absolute bottom-2 right-2 rounded-sm bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
								{t("{{num}} images", { num: totalImages })}
							</div>
						)}
					</div>

					<div className="flex flex-col gap-1 p-3">
						<h3 className="text-sm font-medium leading-snug truncate">
							{character.name}
						</h3>
						<p className="text-muted-foreground line-clamp-2 text-xs">
							{character.description || t("No description")}
						</p>
						{totalGenerations > 0 && (
							<span className="text-muted-foreground text-[10px]">
								{t("{{num}} generations", {
									num: totalGenerations,
								})}
							</span>
						)}
					</div>
				</div>
			</button>

			<DropdownMenu open={isMenuOpen} onOpenChange={setIsMenuOpen}>
				<DropdownMenuTrigger asChild>
					<Button
						type="button"
						variant="background"
						size="icon"
						className={cn(
							"absolute top-2 right-2 z-10",
							isMenuOpen
								? "opacity-100"
								: "opacity-0 group-hover:opacity-100",
						)}
						onClick={(event) => {
							event.stopPropagation();
						}}
						onKeyDown={(event) => {
							if (event.key === "Enter" || event.key === " ") {
								event.stopPropagation();
							}
						}}
					>
						<HugeiconsIcon icon={MoreHorizontalIcon} />
					</Button>
				</DropdownMenuTrigger>
				<DropdownMenuContent align="end">
					<DropdownMenuItem
						onClick={(event) => {
							event.stopPropagation();
							onEdit();
							setIsMenuOpen(false);
						}}
					>
						<HugeiconsIcon icon={Edit03Icon} />
						{t("Edit")}
					</DropdownMenuItem>
					<DropdownMenuItem
						variant="destructive"
						onClick={(event) => {
							event.stopPropagation();
							onDelete();
							setIsMenuOpen(false);
						}}
					>
						<HugeiconsIcon icon={Delete02Icon} />
						{t("Delete")}
					</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>
		</div>
	);
}
