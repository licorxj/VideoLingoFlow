"use client";

import { useEffect, useRef } from "react";
import { useEditor } from "@/hooks/use-editor";
import { storageService } from "@/services/storage/service";
import type { MediaType } from "@/types/assets";
import type { TProject } from "@/types/project";

const getApiBaseUrl = () => process.env.NEXT_PUBLIC_VIDEOLINGO_API_URL || window.location.origin;

const TASK_PROJECT_BRIDGE_VERSION = 1;
const SERVER_SAVE_DEBOUNCE_MS = 1200;
const MEDIA_FETCH_RETRIES = 3;

type TaskAsset = {
	id: string;
	name: string;
	type: "video" | "audio" | "image" | "subtitle";
	mime_type?: string;
	duration?: number;
	width?: number;
	height?: number;
};

type LoadTaskProjectMessage = {
	type: "videolingo:load-task-project";
	version: number;
	taskId: string;
	project: Record<string, unknown>;
	assets: TaskAsset[];
	revision: number;
};

type PreserveLocalProjectMessage = {
	type: "videolingo:preserve-local-project";
	version: number;
	taskId: string;
};

type RequestSaveMessage = {
	type: "videolingo:request-save";
	version: number;
	taskId: string;
};

function isLoadTaskProjectMessage(value: unknown): value is LoadTaskProjectMessage {
	return Boolean(
		value &&
		typeof value === "object" &&
		(value as LoadTaskProjectMessage).type === "videolingo:load-task-project" &&
		(value as LoadTaskProjectMessage).version === TASK_PROJECT_BRIDGE_VERSION &&
		typeof (value as LoadTaskProjectMessage).taskId === "string" &&
		Array.isArray((value as LoadTaskProjectMessage).assets) &&
		typeof (value as LoadTaskProjectMessage).project === "object" &&
		typeof (value as LoadTaskProjectMessage).revision === "number",
	);
}

function isPreserveLocalProjectMessage(value: unknown): value is PreserveLocalProjectMessage {
	return Boolean(
		value &&
			typeof value === "object" &&
			(value as PreserveLocalProjectMessage).type === "videolingo:preserve-local-project" &&
			(value as PreserveLocalProjectMessage).version === TASK_PROJECT_BRIDGE_VERSION &&
			typeof (value as PreserveLocalProjectMessage).taskId === "string",
	);
}

function isRequestSaveMessage(value: unknown): value is RequestSaveMessage {
	return Boolean(
		value &&
			typeof value === "object" &&
			(value as RequestSaveMessage).type === "videolingo:request-save" &&
			(value as RequestSaveMessage).version === TASK_PROJECT_BRIDGE_VERSION &&
			typeof (value as RequestSaveMessage).taskId === "string",
	);
}

function toDate(value: unknown): Date {
	const date = new Date(typeof value === "string" ? value : Date.now());
	return Number.isNaN(date.getTime()) ? new Date() : date;
}

function toProject(taskId: string, project: Record<string, unknown>): TProject {
	const snapshot = structuredClone(project) as unknown as TProject;
	snapshot.metadata.id = taskId;
	snapshot.metadata.createdAt = toDate(snapshot.metadata.createdAt);
	snapshot.metadata.updatedAt = toDate(snapshot.metadata.updatedAt);
	for (const scene of snapshot.scenes) {
		scene.createdAt = toDate(scene.createdAt);
		scene.updatedAt = toDate(scene.updatedAt);
	}
	return snapshot;
}

function referencedMediaIds(project: Record<string, unknown>): Set<string> {
	const mediaIds = new Set<string>();
	const scenes = Array.isArray(project.scenes) ? project.scenes : [];
	for (const scene of scenes) {
		if (!scene || typeof scene !== "object") continue;
		const tracks = Array.isArray((scene as { tracks?: unknown }).tracks) ? (scene as { tracks: unknown[] }).tracks : [];
		for (const track of tracks) {
			if (!track || typeof track !== "object") continue;
			const elements = Array.isArray((track as { elements?: unknown }).elements) ? (track as { elements: unknown[] }).elements : [];
			for (const element of elements) {
				const mediaId = element && typeof element === "object" ? (element as { mediaId?: unknown }).mediaId : undefined;
				if (typeof mediaId === "string") mediaIds.add(mediaId);
			}
		}
	}
	return mediaIds;
}

async function fetchMediaAsset(taskId: string, asset: TaskAsset): Promise<Blob> {
	let lastError: unknown;
	for (let attempt = 0; attempt < MEDIA_FETCH_RETRIES; attempt += 1) {
		try {
			const response = await fetch(
				`${getApiBaseUrl()}/api/editor/tasks/${encodeURIComponent(taskId)}/assets/${encodeURIComponent(asset.id)}/stream`,
				{ cache: "no-store" },
			);
			if (!response.ok) {
				throw new Error(`Failed to load ${asset.name} (${response.status})`);
			}
			return await response.blob();
		} catch (error) {
			lastError = error;
			if (attempt + 1 < MEDIA_FETCH_RETRIES) {
				await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)));
			}
		}
	}
	throw lastError instanceof Error ? lastError : new Error(`Failed to load ${asset.name}`);
}

export function VideoLingoTaskBridge() {
	const editor = useEditor();
	const taskIdRef = useRef<string | null>(null);
	const revisionRef = useRef<number | null>(null);
	const isLoadingRef = useRef(false);
	const isConflictRef = useRef(false);
	const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const savedProjectRef = useRef<string | null>(null);
	const saveToServerRef = useRef<() => Promise<void>>(async () => {});
	const isSavingRef = useRef(false);

	const postStatus = (type: string, payload: Record<string, unknown> = {}) => {
		if (window.parent === window) return;
		window.parent.postMessage({ type, version: TASK_PROJECT_BRIDGE_VERSION, taskId: taskIdRef.current, ...payload }, window.location.origin);
	};

	const reportDebug = (hypothesisId: string, msg: string, data: Record<string, unknown> = {}) => {
		// #region debug-point A-D:bridge-project-load
		fetch("http://127.0.0.1:7777/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId: "cutia-project-load", runId: "pre-fix", hypothesisId, location: "videolingo-task-bridge.tsx", msg: `[DEBUG] ${msg}`, data, ts: Date.now() }) }).catch(() => {});
		// #endregion
	};

	useEffect(() => {
		const saveToServer = async () => {
			const taskId = taskIdRef.current;
			const revision = revisionRef.current;
			const project = editor.project.getActiveOrNull();
			if (!taskId || revision === null || !project || project.metadata.id !== taskId || isLoadingRef.current || isConflictRef.current || isSavingRef.current) return;
			const serializedProject = JSON.stringify(project);
			if (serializedProject === savedProjectRef.current) return;

			isSavingRef.current = true;
			postStatus("videolingo:project-save-started");
			try {
				const response = await fetch(`${getApiBaseUrl()}/api/editor/tasks/${encodeURIComponent(taskId)}/project`, {
					method: "PUT",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ project, expected_revision: revision }),
				});
				if (response.status === 409) {
					const conflict = (await response.json()) as { revision?: number };
					isConflictRef.current = true;
					postStatus("videolingo:project-save-conflict", { revision: conflict.revision });
					return;
				}
				if (!response.ok) throw new Error(`Server save failed (${response.status})`);
				const snapshot = (await response.json()) as { revision: number };
				revisionRef.current = snapshot.revision;
				savedProjectRef.current = serializedProject;
				postStatus("videolingo:project-save-complete", { revision: snapshot.revision });
			} catch (error) {
				postStatus("videolingo:project-save-failed", { message: error instanceof Error ? error.message : "Server save failed" });
			} finally {
				isSavingRef.current = false;
			}
		};
		saveToServerRef.current = saveToServer;

		const queueServerSave = () => {
			if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
			saveTimerRef.current = setTimeout(() => {
				saveTimerRef.current = null;
				void saveToServer();
			}, SERVER_SAVE_DEBOUNCE_MS);
		};

		const unsubscribe = editor.project.subscribe(queueServerSave);
		return () => {
			unsubscribe();
			if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
		};
	}, [editor]);

	useEffect(() => {
		const handleMessage = async (event: MessageEvent<unknown>) => {
			if (event.origin !== window.location.origin) {
				reportDebug("D", "Rejected cross-origin message", { origin: event.origin });
				return;
			}
			if (isPreserveLocalProjectMessage(event.data)) {
				if (event.data.taskId === taskIdRef.current) {
					isConflictRef.current = true;
					postStatus("videolingo:project-save-local-only");
				}
				return;
			}
			if (isRequestSaveMessage(event.data)) {
				if (event.data.taskId !== taskIdRef.current) return;
				if (saveTimerRef.current) {
					clearTimeout(saveTimerRef.current);
					saveTimerRef.current = null;
				}
				if (isSavingRef.current) return;
				const project = editor.project.getActiveOrNull();
				const serializedProject = project ? JSON.stringify(project) : "";
				if (serializedProject === savedProjectRef.current) {
					postStatus("videolingo:project-save-complete", { revision: revisionRef.current });
					return;
				}
				void saveToServerRef.current();
				return;
			}
			if (!isLoadTaskProjectMessage(event.data)) {
				reportDebug("D", "Rejected task project message", { type: (event.data as { type?: unknown } | null)?.type });
				return;
			}

			const { taskId, project, assets, revision } = event.data;
			reportDebug("A", "Bridge received task project", { taskId, revision, assetCount: assets.length });
			isLoadingRef.current = true;
			isConflictRef.current = false;
			taskIdRef.current = taskId;
			revisionRef.current = revision;
			savedProjectRef.current = JSON.stringify(project);
			try {
				const mediaIds = referencedMediaIds(project);
				reportDebug("B", "Bridge resolved project media", { taskId, referencedMediaCount: mediaIds.size });
				const mediaAssets = await Promise.all(
					assets.filter((asset) => asset.type !== "subtitle" && mediaIds.has(asset.id)).map(async (asset) => {
							const blob = await fetchMediaAsset(taskId, asset);
							return {
								id: asset.id,
								name: asset.name,
								type: asset.type as MediaType,
								file: new File([blob], asset.name, { type: blob.type || asset.mime_type || "application/octet-stream" }),
								duration: asset.duration,
								width: asset.width,
								height: asset.height,
							};
						}),
				);
				const normalizedProject = toProject(taskId, project);
				reportDebug("C", "Bridge saving local project", { taskId, mediaCount: mediaAssets.length });
				await storageService.deleteProjectMedia({ projectId: taskId });
				for (const mediaAsset of mediaAssets) {
					await storageService.saveMediaAsset({ projectId: taskId, mediaAsset });
				}
				await storageService.saveProject({ project: normalizedProject });
				await editor.project.loadProject({ id: taskId });
				reportDebug("C", "Bridge loaded local project", { taskId });
				window.parent.postMessage({ type: "videolingo:load-task-project-complete", version: TASK_PROJECT_BRIDGE_VERSION, taskId }, event.origin);
			} catch (error) {
				reportDebug("B", "Bridge project load failed", { taskId, message: error instanceof Error ? error.message : "Load failed" });
				window.parent.postMessage(
					{ type: "videolingo:load-task-project-failed", version: TASK_PROJECT_BRIDGE_VERSION, taskId, message: error instanceof Error ? error.message : "Load failed" },
					event.origin,
				);
			} finally {
				isLoadingRef.current = false;
			}
		};

		window.addEventListener("message", handleMessage);
		if (window.parent !== window) {
			reportDebug("A", "Bridge ready", { href: window.location.href });
			window.parent.postMessage({ type: "videolingo:editor-ready" }, window.location.origin);
		}
		return () => window.removeEventListener("message", handleMessage);
	}, [editor]);

	return null;
}
