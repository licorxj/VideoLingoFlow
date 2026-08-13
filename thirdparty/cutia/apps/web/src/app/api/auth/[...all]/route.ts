import { auth, isAuthEnabled } from "@/lib/auth/server";
import { NextResponse } from "next/server";
import { toNextJsHandler } from "better-auth/next-js";

const authHandlers = isAuthEnabled() ? toNextJsHandler(auth) : null;

function buildAuthDisabledResponse() {
	return NextResponse.json(
		{
			error:
				"Auth is disabled. Set DATABASE_URL and BETTER_AUTH_SECRET to enable auth.",
		},
		{ status: 503 },
	);
}

export const GET = authHandlers?.GET ?? buildAuthDisabledResponse;
export const POST = authHandlers?.POST ?? buildAuthDisabledResponse;
