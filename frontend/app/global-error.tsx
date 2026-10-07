"use client";

import { useEffect } from "react";

/** Root-level boundary — replaces the whole document when the root layout
 * itself throws (theme script, providers). Renders without theme classes so
 * it can't recurse into the same crash; inline styles keep it dark-first. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          background: "#0f1011",
          color: "#f7f8f8",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "0 1.5rem",
        }}
      >
        <h2 style={{ fontSize: "1.125rem", fontWeight: 600, margin: 0 }}>
          Something went wrong
        </h2>
        <p
          style={{
            margin: 0,
            maxWidth: "22rem",
            fontSize: "0.875rem",
            color: "#8a8f98",
          }}
        >
          The app hit an unexpected error. Reload to try again.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            marginTop: "0.5rem",
            padding: "0.5rem 1rem",
            borderRadius: "0.75rem",
            border: "1px solid #23252a",
            background: "#3ec6ad",
            color: "#072e27",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
