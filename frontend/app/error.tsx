"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

/** Segment-level boundary — catches render errors in any page so a crash
 * (bad server payload, malformed thread) shows a recovery surface instead
 * of a blank frame. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <h2 className="text-lg font-semibold text-foreground">
        Something went wrong
      </h2>
      <p className="max-w-sm text-sm text-muted-foreground">
        The page hit an unexpected error. Your conversations are safe — try
        again or head back home.
      </p>
      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button variant="outline" onClick={() => router.push("/")}>
          Home
        </Button>
      </div>
    </div>
  );
}
