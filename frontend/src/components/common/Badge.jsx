const VARIANTS = {
  moderate: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
  high: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  extreme: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
  modis: "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/30",
  viirs: "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 border-yellow-500/30",
  neutral:
    "bg-(--surface-secondary) text-(--text-secondary) border-(--border-color)",
};

export default function Badge({ children, variant = "neutral" }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${VARIANTS[variant] ?? VARIANTS.neutral}`}
    >
      {children}
    </span>
  );
}
