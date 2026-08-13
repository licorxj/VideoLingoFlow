"use client";

import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { Link } from "@/lib/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CharacterCard } from "@/components/characters/character-card";
import { CharacterCreatorDialog } from "@/components/characters/character-creator";
import { CharacterDetailDialog } from "@/components/characters/character-detail";
import { useCharacterStore } from "@/stores/character-store";
import { ThemeToggle } from "@/components/theme-toggle";
import { LanguageToggle } from "@/components/language-toggle";
import type { AICharacter } from "@/types/character";
import { HugeiconsIcon } from "@hugeicons/react";
import {
	PlusSignIcon,
	Search01Icon,
	UserIcon,
} from "@hugeicons/core-free-icons";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export default function CharactersPage() {
	const { t } = useTranslation();
	const { characters, deleteCharacter } = useCharacterStore();

	const [searchQuery, setSearchQuery] = useState("");
	const [isCreateOpen, setIsCreateOpen] = useState(false);
	const [editingCharacter, setEditingCharacter] =
		useState<AICharacter | null>(null);
	const [viewingCharacter, setViewingCharacter] =
		useState<AICharacter | null>(null);
	const [deletingCharacter, setDeletingCharacter] =
		useState<AICharacter | null>(null);

	const filteredCharacters = searchQuery.trim()
		? characters.filter(
				(character) =>
					character.name
						.toLowerCase()
						.includes(searchQuery.toLowerCase()) ||
					character.description
						.toLowerCase()
						.includes(searchQuery.toLowerCase()),
			)
		: characters;

	const handleDeleteConfirm = () => {
		if (deletingCharacter) {
			deleteCharacter({ id: deletingCharacter.id });
			if (viewingCharacter?.id === deletingCharacter.id) {
				setViewingCharacter(null);
			}
			setDeletingCharacter(null);
		}
	};

	const handleEditFromDetail = () => {
		if (viewingCharacter) {
			setEditingCharacter(viewingCharacter);
			setViewingCharacter(null);
		}
	};

	return (
		<div className="bg-background min-h-screen">
			<header className="sticky top-0 z-20 px-8 bg-background flex flex-col gap-2">
				<div className="flex items-center justify-between h-16 pt-2">
					<Breadcrumb>
						<BreadcrumbList>
							<BreadcrumbItem>
								<BreadcrumbLink asChild>
									<Link
										href="/"
										className="text-sm sm:text-base"
									>
										{t("Home")}
									</Link>
								</BreadcrumbLink>
							</BreadcrumbItem>
							<BreadcrumbSeparator />
							<BreadcrumbItem>
								<BreadcrumbLink asChild>
									<Link
										href="/projects"
										className="text-sm sm:text-base"
									>
										{t("All projects")}
									</Link>
								</BreadcrumbLink>
							</BreadcrumbItem>
							<BreadcrumbSeparator />
							<BreadcrumbItem>
								<BreadcrumbPage className="text-sm sm:text-base font-medium">
									{t("Characters")}
								</BreadcrumbPage>
							</BreadcrumbItem>
						</BreadcrumbList>
					</Breadcrumb>

					<div className="flex items-center gap-3 md:gap-4">
						<LanguageToggle />
						<ThemeToggle />
						<div className="relative hidden md:block">
							<HugeiconsIcon
								icon={Search01Icon}
								className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2"
								aria-hidden="true"
							/>
							<Input
								placeholder={t("Search...")}
								value={searchQuery}
								onChange={(event) =>
									setSearchQuery(event.target.value)
								}
								size="lg"
								className="pl-9"
							/>
						</div>
						<Button
							size="lg"
							className="flex px-5 md:px-6"
							onClick={() => setIsCreateOpen(true)}
							onKeyDown={(event) => {
								if (event.key === "Enter")
									setIsCreateOpen(true);
							}}
						>
							<span className="text-sm font-medium hidden md:block">
								{t("New Character")}
							</span>
							<span className="text-sm font-medium block md:hidden">
								{t("New")}
							</span>
						</Button>
					</div>
				</div>

				<div className="relative block md:hidden mb-4">
					<HugeiconsIcon
						icon={Search01Icon}
						className="text-muted-foreground pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2"
						aria-hidden="true"
					/>
					<Input
						placeholder={t("Search...")}
						value={searchQuery}
						onChange={(event) => setSearchQuery(event.target.value)}
						size="lg"
						className="pl-9"
					/>
				</div>
			</header>

			<main className="mx-auto px-4 pt-2 pb-6 flex flex-col gap-4">
				{filteredCharacters.length === 0 ? (
					<EmptyState
						hasSearch={searchQuery.trim().length > 0}
						searchQuery={searchQuery}
						onClearSearch={() => setSearchQuery("")}
						onCreateNew={() => setIsCreateOpen(true)}
					/>
				) : (
					<div className="xs:grid-cols-2 grid grid-cols-1 gap-6 sm:grid-cols-3 lg:grid-cols-4 px-4">
						{filteredCharacters.map((character) => (
							<CharacterCard
								key={character.id}
								character={character}
								onClick={() => setViewingCharacter(character)}
								onEdit={() => setEditingCharacter(character)}
								onDelete={() =>
									setDeletingCharacter(character)
								}
							/>
						))}
					</div>
				)}
			</main>

			<CharacterCreatorDialog
				isOpen={isCreateOpen}
				onOpenChange={setIsCreateOpen}
			/>

			<CharacterCreatorDialog
				key={editingCharacter?.id}
				isOpen={editingCharacter !== null}
				onOpenChange={(open) => {
					if (!open) setEditingCharacter(null);
				}}
				editCharacter={editingCharacter}
			/>

			<CharacterDetailDialog
				character={viewingCharacter}
				isOpen={viewingCharacter !== null}
				onOpenChange={(open) => {
					if (!open) setViewingCharacter(null);
				}}
				onEdit={handleEditFromDetail}
			/>

			<AlertDialog
				open={deletingCharacter !== null}
				onOpenChange={(open) => {
					if (!open) setDeletingCharacter(null);
				}}
			>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>
							{t("Delete Character")}
						</AlertDialogTitle>
						<AlertDialogDescription>
							{t(
								'Are you sure you want to delete "{{name}}"? This will remove all reference images and generation history for this character.',
								{ name: deletingCharacter?.name },
							)}
						</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogCancel>{t("Cancel")}</AlertDialogCancel>
						<AlertDialogAction onClick={handleDeleteConfirm}>
							{t("Delete")}
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</div>
	);
}

function EmptyState({
	hasSearch,
	searchQuery,
	onClearSearch,
	onCreateNew,
}: {
	hasSearch: boolean;
	searchQuery: string;
	onClearSearch: () => void;
	onCreateNew: () => void;
}) {
	const { t } = useTranslation();

	if (hasSearch) {
		return (
			<div className="flex flex-col items-center justify-center gap-5 py-16 text-center">
				<HugeiconsIcon
					icon={Search01Icon}
					className="text-muted-foreground size-16 bg-accent/35 border rounded-md p-4"
				/>
				<div className="flex flex-col items-center gap-3">
					<h3 className="text-lg font-medium">
						{t("No results found")}
					</h3>
					<p className="text-muted-foreground max-w-md">
						{t(
							'Your search for "{{query}}" did not return any results.',
							{ query: searchQuery },
						)}
					</p>
				</div>
				<Button onClick={onClearSearch} variant="outline" size="lg">
					{t("Clear search")}
				</Button>
			</div>
		);
	}

	return (
		<div className="flex flex-col items-center justify-center gap-6 py-16 text-center">
			<div className="flex flex-col items-center gap-2">
				<div className="bg-muted/30 flex size-16 items-center justify-center rounded-full">
					<HugeiconsIcon
						icon={UserIcon}
						className="text-muted-foreground size-8"
					/>
				</div>
				<h3 className="text-lg font-medium">
					{t("No characters yet")}
				</h3>
				<p className="text-muted-foreground max-w-md">
					{t(
						"Create AI character cards with front-facing portraits. Use them as reference images for consistent AI generation.",
					)}
				</p>
			</div>
			<Button size="lg" className="gap-2" onClick={onCreateNew}>
				<HugeiconsIcon icon={PlusSignIcon} />
				{t("Create your first character")}
			</Button>
		</div>
	);
}
