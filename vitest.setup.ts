import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Testing Library normally unmounts between tests by itself, but only when
 * vitest runs with `globals: true` — and this project does not. Without this,
 * a second `render` in the same file leaves the first one in the document and
 * every query fails with "found multiple elements".
 */
afterEach(cleanup);
