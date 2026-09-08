"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { useApp } from "@/app/providers";
import { Input } from "@/components/ui/input";
import { ApiError, type PublicIdentity } from "@/lib/api/port";

/**
 * Shell user search: GET /users/search?q= with a compact result list that
 * navigates to `/profile/[username]`. Follow stays on the profile page.
 */
export function UserSearch() {
  const { gateway } = useApp();
  const router = useRouter();
  const listId = useId();
  const rootRef = useRef<HTMLFormElement>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PublicIdentity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (
        rootRef.current !== null &&
        event.target instanceof Node &&
        !rootRef.current.contains(event.target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  async function runSearch(term: string) {
    const trimmed = term.trim();
    if (trimmed.length < 1 || trimmed.length > 50) {
      setResults([]);
      setError(trimmed.length > 50 ? "Search is limited to 50 characters." : null);
      setOpen(trimmed.length > 50);
      return;
    }
    setPending(true);
    setError(null);
    try {
      const items = await gateway.searchUsers(term);
      setResults(items);
      setOpen(true);
      if (items.length === 0) setError("No users found.");
    } catch (err) {
      setResults([]);
      setOpen(true);
      if (err instanceof ApiError && err.status === 401) return;
      setError("Couldn't search users. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      ref={rootRef}
      role="search"
      className="relative min-w-0 flex-1"
      onSubmit={(event) => {
        event.preventDefault();
        void runSearch(query);
      }}
    >
      <Input
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setError(null);
        }}
        onFocus={() => {
          if (results.length > 0 || error !== null) setOpen(true);
        }}
        aria-label="Search users"
        aria-controls={listId}
        aria-expanded={open}
        aria-autocomplete="list"
        placeholder="Search users"
        maxLength={50}
        autoComplete="off"
      />
      {open ? (
        <div
          id={listId}
          role="listbox"
          aria-label="Search results"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {pending ? (
            <p className="px-2 py-1.5 text-sm text-muted-foreground">Searching…</p>
          ) : null}
          {!pending && error !== null ? (
            <p role="status" className="px-2 py-1.5 text-sm text-muted-foreground">
              {error}
            </p>
          ) : null}
          {!pending && error === null
            ? results.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="option"
                  className="flex w-full flex-col items-start rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent"
                  onClick={() => {
                    setOpen(false);
                    setQuery("");
                    setResults([]);
                    router.push(`/profile/${item.username}`);
                  }}
                >
                  <span className="font-medium">{item.displayName}</span>
                  <span className="text-xs text-muted-foreground">
                    @{item.username}
                  </span>
                </button>
              ))
            : null}
        </div>
      ) : null}
    </form>
  );
}
