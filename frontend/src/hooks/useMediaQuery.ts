import { useEffect, useState } from "react";

/** Subscribe to a CSS media query and return whether it currently matches. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    setMatches(mql.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}

/** True when the viewport is narrower than Tailwind's `md` breakpoint (768px). */
export function useIsMobile(): boolean {
  return useMediaQuery("(max-width: 767px)");
}
