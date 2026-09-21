import { cn } from "@/lib/utils";

export function SparkMark({
  className,
  animate = false,
}: {
  className?: string;
  /** Pop/rotate pulse — the live "working" state of the mark. */
  animate?: boolean;
}) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="currentColor"
      className={cn(className, animate && "spark-mark-live")}
      aria-hidden="true"
    >
      <path d="M16 0l3.8 12.2L32 16l-12.2 3.8L16 32l-3.8-12.2L0 16l12.2-3.8z" />
    </svg>
  );
}
