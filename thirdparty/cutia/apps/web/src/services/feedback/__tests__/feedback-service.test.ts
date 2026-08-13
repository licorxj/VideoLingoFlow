import { beforeEach, describe, expect, mock, test } from "bun:test";

const initOpenapiSDK = mock(() => {});
const submitSurvey = mock(async () => ({ success: true }));

mock.module("tianji-client-sdk", () => ({
	initOpenapiSDK,
	submitSurvey,
}));

import {
	FEEDBACK_TIANJI_ENDPOINT,
	FEEDBACK_TIANJI_SURVEY_ID,
	FEEDBACK_TIANJI_WORKSPACE_ID,
} from "@/constants/feedback-constants";

async function loadService() {
	const mod = await import("../feedback-service");
	return mod;
}

describe("feedback-service", () => {
	beforeEach(() => {
		initOpenapiSDK.mockClear();
		submitSurvey.mockClear();
	});

	test("initializes SDK once and submits the survey with correct args", async () => {
		const { submitFeedback, __resetForTests } = await loadService();
		__resetForTests();

		await submitFeedback({ content: "Hello", contact: "me@example.com" });

		expect(initOpenapiSDK).toHaveBeenCalledTimes(1);
		expect(initOpenapiSDK).toHaveBeenCalledWith(FEEDBACK_TIANJI_ENDPOINT);
		expect(submitSurvey).toHaveBeenCalledTimes(1);
		expect(submitSurvey).toHaveBeenCalledWith(
			FEEDBACK_TIANJI_WORKSPACE_ID,
			FEEDBACK_TIANJI_SURVEY_ID,
			{ content: "Hello", contact: "me@example.com" },
		);
	});

	test("does not re-initialize SDK on subsequent submits", async () => {
		const { submitFeedback, __resetForTests } = await loadService();
		__resetForTests();

		await submitFeedback({ content: "First" });
		await submitFeedback({ content: "Second", contact: "x" });

		expect(initOpenapiSDK).toHaveBeenCalledTimes(1);
		expect(submitSurvey).toHaveBeenCalledTimes(2);
	});

	test("passes empty string when contact is omitted", async () => {
		const { submitFeedback, __resetForTests } = await loadService();
		__resetForTests();

		await submitFeedback({ content: "No contact" });

		expect(submitSurvey).toHaveBeenCalledWith(
			FEEDBACK_TIANJI_WORKSPACE_ID,
			FEEDBACK_TIANJI_SURVEY_ID,
			{ content: "No contact", contact: "" },
		);
	});

	test("propagates errors from submitSurvey", async () => {
		const { submitFeedback, __resetForTests } = await loadService();
		__resetForTests();
		submitSurvey.mockImplementationOnce(async () => {
			throw new Error("network down");
		});

		await expect(
			submitFeedback({ content: "Will fail" }),
		).rejects.toThrow("network down");
	});
});
