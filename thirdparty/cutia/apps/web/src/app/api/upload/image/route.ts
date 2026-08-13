import { type NextRequest, NextResponse } from "next/server";
import { generateUploadKey, isR2Configured, uploadToR2 } from "@/lib/r2/upload";

const MAX_FILE_SIZE = 4 * 1024 * 1024; // 4MB
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

export async function POST(request: NextRequest) {
	try {
		if (!isR2Configured()) {
			return NextResponse.json(
				{ error: "R2 storage is not configured" },
				{ status: 503 },
			);
		}

		const formData = await request.formData();
		const file = formData.get("file");

		if (!(file instanceof File)) {
			return NextResponse.json(
				{
					error:
						"No file provided. Send a file via multipart form field 'file'.",
				},
				{ status: 400 },
			);
		}

		if (!ALLOWED_TYPES.includes(file.type)) {
			return NextResponse.json(
				{
					error: `Invalid file type '${file.type}'. Allowed: ${ALLOWED_TYPES.join(", ")}`,
				},
				{ status: 400 },
			);
		}

		if (file.size > MAX_FILE_SIZE) {
			return NextResponse.json(
				{
					error: `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB).`,
				},
				{ status: 400 },
			);
		}

		const key = generateUploadKey({ filename: file.name });
		const arrayBuffer = await file.arrayBuffer();

		const url = await uploadToR2({
			data: arrayBuffer,
			key,
			contentType: file.type,
		});

		return NextResponse.json({ url });
	} catch (error) {
		console.error("Image upload error:", error);
		return NextResponse.json(
			{ error: error instanceof Error ? error.message : "Upload failed" },
			{ status: 500 },
		);
	}
}
