import type { FunctionReturnType } from "convex/server";

import type { api } from "../../../convex/_generated/api";

/** Exactly what `convex/site.ts` returns, so the dashboard and the page cannot
 *  drift from the query that feeds them. */
export type Summary = FunctionReturnType<typeof api.site.summary>;
