/**
 * Merge Tailwind utility classes with conflict resolution.
 *
 * Built on `clsx` (truthy filter + array/object expansion) and
 * `tailwind-merge` (last-write-wins for conflicting Tailwind families,
 * e.g. `cn("p-4", "p-8")` → `"p-8"`).
 *
 * When to reach for this:
 *   - Combining a base style with a conditional override and you want
 *     the override to win even when it's the same utility family:
 *       cn("rounded-md", isPill && "rounded-full")
 *   - Inside a `class-variance-authority` (cva) consumer that also
 *     accepts a user-supplied `class` prop and you need both merged.
 *
 * When NOT to bother:
 *   - Static `:class="[a, b]"` arrays in templates — Vue already
 *     concatenates them; you only need cn() when twMerge's
 *     deduplication actually changes the result.
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
